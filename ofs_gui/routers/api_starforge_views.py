import os
import sys
import io
import asyncio
import json
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from core.config import STARFORGE_PATH, BASE_DIR, get_starforge_python
import core.state as state

router = APIRouter()

@router.get("/api/starforge/flat_view")
async def starforge_flat_view(dir: str, session: str = "", file: str = "", out_dir: str = "", cx: str = "", cy: str = ""):
    abs_dir = os.path.abspath(os.path.expanduser(dir))
    log_file = os.path.join(abs_dir, "shutter_log.json")
    
    file_options = []
    file_map = {}
    
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                logs = json.load(f)
            for record in logs:
                if not session or record.get("session_id") == session:
                    fname = record.get("record", {}).get("file", {}).get("name")
                    fpath = record.get("record", {}).get("file", {}).get("path", "")
                    if fname:
                        full_p = os.path.join(fpath if fpath else abs_dir, fname)
                        if os.path.exists(full_p) and fname not in file_map:
                            file_options.append(fname)
                            file_map[fname] = full_p
        except Exception:
            pass
            
    if not file_options and os.path.isdir(abs_dir):
        for f in os.listdir(abs_dir):
            if f.lower().endswith(('.fits', '.fit', '.dng', '.raw', '.cr2', '.nef', '.jpg', '.jpeg', '.png')):
                if f not in file_map:
                    full_p = os.path.join(abs_dir, f)
                    file_options.append(f)
                    file_map[f] = full_p
                    
    stacked_files = []
    search_dirs = []
    if out_dir:
        search_dirs.append(os.path.abspath(os.path.expanduser(out_dir)))
    search_dirs.append(abs_dir)
    
    # Remove duplicates
    search_dirs = list(dict.fromkeys(search_dirs))
    
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            prefix = "master_flat_"
            try:
                for f in os.listdir(s_dir):
                    if f.startswith(prefix) and f.lower().endswith(('.fits', '.fit')):
                        if not session or f"_{session}" in f:
                            if f not in stacked_files:
                                stacked_files.append(f)
                                if f not in file_map:
                                    file_map[f] = os.path.join(s_dir, f)
            except Exception:
                pass

    if not file_options and not stacked_files:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><h3>Error: No flat images found in the specified directory/session.</h3></body></html>", status_code=404)

    if file and file in file_map:
        selected_filename = file
    elif stacked_files:
        selected_filename = stacked_files[0]
    else:
        selected_filename = file_options[0]

    target_file = file_map[selected_filename]
    
    options_html = ""
    if stacked_files:
        options_html += '<div class="list-title" style="padding: 6px 10px;">STACKED FILE</div>\n'
        for sf in stacked_files:
            sel = " selected" if sf == selected_filename else ""
            options_html += f"""<div class="list-item{sel}" onclick="changeFile('{sf}')"><div class="file-name" style="color: var(--accent-gold); font-weight: 600;">{sf}</div></div>\n"""
        options_html += '<div class="list-title" style="margin-top: 8px; border-top: 1px solid var(--glass-border); padding: 6px 10px;">FILES</div>\n'
    else:
        options_html += '<div class="list-title" style="padding: 6px 10px;">FILES</div>\n'

    for opt in file_options:
        sel = " selected" if opt == selected_filename else ""
        options_html += f"""<div class="list-item{sel}" onclick="changeFile('{opt}')"><div class="file-name">{opt}</div></div>\n"""

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
cx = int(cx_str) if cx_str.lstrip("-").isdigit() else -1
cy = int(cy_str) if cy_str.lstrip("-").isdigit() else -1
data = None

try:
    ext = file_path.lower().split('.')[-1]
    if ext in ['fits', 'fit']:
        if has_astropy:
            with fits.open(file_path) as hdul:
                for hdu in hdul:
                    if hdu.data is not None:
                        d = hdu.data
                        if d.ndim == 3:
                            data = np.mean(d, axis=0)
                        else:
                            data = d
                        break
    elif ext in ['dng', 'cr2', 'nef', 'arw', 'raw']:
        if has_rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=16)
                data = np.mean(rgb, axis=2)
    else:
        img = Image.open(file_path).convert('L')
        data = np.array(img)

    if data is None:
        print("<html><body><h3>Error: Unsupported file format or missing libraries.</h3></body></html>")
        sys.exit(0)

    h, w = data.shape
    scale_2d = max(1, round(w / 640))
    scale_3d = max(1, round(w / 150))
    
    data_small_2d = data[::scale_2d, ::scale_2d]
    data_small_3d = data[::scale_3d, ::scale_3d]

    z_data = data_small_2d.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    z_data_3d = data_small_3d.astype(float)
    z_data_3d = np.nan_to_num(z_data_3d, nan=0.0, posinf=0.0, neginf=0.0)
    
    z_max = float(np.max(z_data))
    if z_max <= 0:
        z_max = 255.0

    # Calculate center slices for 2D plots
    ch, cw = z_data.shape
    mid_y, mid_x = ch // 2, cw // 2
    x_slice = z_data[mid_y, :].tolist()
    y_slice = z_data[:, mid_x].tolist()

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Flat Image 3D View</title>
        <link rel="stylesheet" href="/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <style>
            .flat-layout-3col {
                display: grid;
                grid-template-columns: 20% 50% 1fr;
                gap: 1rem;
                height: calc(100vh - 120px);
            }
            .col-files { background: var(--bg-sidebar); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-center { position: relative; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-right { display: flex; flex-direction: column; gap: 1rem; height: calc(100vh - 120px); }
            .side-plot { flex: 1; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; overflow: hidden; position: relative; }
            #plot { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
            /* Adjust list-item height and font based on previous request while keeping LOGDATA design */
            .list-item { padding: 8px 8px !important; }
            .file-name { font-size: 0.68rem !important; }
        </style>
        <script>
            function changeFile(filename) {
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('file', filename);
                window.location.search = urlParams.toString();
            }
        </script>
    </head>
    <body>
        <div class="container" style="max-width: 100%;">
            <header>
                <div class="header-main">
                    <h1>OrionFieldStack <span class="v-tag">Flat Viewer</span></h1>
                </div>
            </header>
            
            <main>
                <div class="flat-layout-3col">
                    <aside class="col-files">
                        <div class="list-container" style="padding: 0; display: flex; flex-direction: column;">
                            __OPTIONS__
                        </div>
                    </aside>
                    <div class="col-center">
                        <div style="position: absolute; top: 10px; right: 10px; z-index: 10; display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.6); padding: 8px 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                            <span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: bold; margin-right: 4px;">Z-AXIS</span>
                            <label style="font-size: 0.75rem; color: var(--text-dim);">Min:</label>
                            <input type="number" id="z-min" value="0" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                            <label style="font-size: 0.75rem; color: var(--text-dim); margin-left: 4px;">Max:</label>
                            <input type="number" id="z-max" value="__ZMAX__" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                        </div>
                        <div id="plot"></div>
                    </div>
                    <div class="col-right">
                        <div id="plot-xz" class="side-plot"></div>
                        <div id="plot-yz" class="side-plot"></div>
                    </div>
                </div>
            </main>
        </div>
        <script>
            var z_data = __ZDATA3D__;
            var x_slice = __XSLICE__;
            var y_slice = __YSLICE__;
 
            // 3D Plot
            var data3d = [{
                z: z_data,
                type: 'surface',
                colorscale: 'Viridis',
                cmin: 0,
                cmax: __ZMAX__,
                showscale: false
            }];
            var aspect_x = z_data[0].length / Math.max(z_data.length, z_data[0].length);
            var aspect_y = z_data.length / Math.max(z_data.length, z_data[0].length);

            var layout3d = {
                autosize: true,
                scene: {
                    xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                    yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                    zaxis: { title: 'Luminance', range: [0, __ZMAX__], autorange: false },
                    aspectmode: 'manual',
                    aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                    camera: {
                        eye: {x: -1.5, y: -1.5, z: 1.2}
                    }
                },
                margin: { l: 0, r: 0, b: 0, t: 0 },
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212'
            };
            Plotly.newPlot('plot', data3d, layout3d, {responsive: true});

            // X-Z Section
            var dataXZ = [
                { y: x_slice, type: 'scatter', mode: 'lines', name: 'Center', line: {color: '#00ff88', dash: 'dash'} },
                { y: x_slice, type: 'scatter', mode: 'lines', name: 'Selected', line: {color: '#ffffff'} }
            ];
            var layoutXZ = {
                title: 'X-Z Section (Center & Selected)',
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff'},
                margin: {t: 40, b: 40, l: 40, r: 20},
                xaxis: { title: 'X', showgrid: true, gridcolor: '#333' },
                yaxis: { title: 'Luminance', showgrid: true, gridcolor: '#333', range: [0, __ZMAX__] },
                showlegend: true,
                legend: { x: 1, xanchor: 'right', y: 1, bgcolor: 'rgba(0,0,0,0)' }
            };
            Plotly.newPlot('plot-xz', dataXZ, layoutXZ, {responsive: true});

            // Y-Z Section
            var dataYZ = [
                { y: y_slice, type: 'scatter', mode: 'lines', name: 'Center', line: {color: '#ff0088', dash: 'dash'} },
                { y: y_slice, type: 'scatter', mode: 'lines', name: 'Selected', line: {color: '#ffffff'} }
            ];
            var layoutYZ = {
                title: 'Y-Z Section (Center & Selected)',
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff'},
                margin: {t: 40, b: 40, l: 40, r: 20},
                xaxis: { title: 'Y', showgrid: true, gridcolor: '#333' },
                yaxis: { title: 'Luminance', showgrid: true, gridcolor: '#333', range: [0, __ZMAX__] },
                showlegend: true,
                legend: { x: 1, xanchor: 'right', y: 1, bgcolor: 'rgba(0,0,0,0)' }
            };
            Plotly.newPlot('plot-yz', dataYZ, layoutYZ, {responsive: true});

            // Add click event for 3D plot to update selected cross-sections
            var plotDiv = document.getElementById('plot');
            plotDiv.on('plotly_click', function(data) {
                if (data.points && data.points.length > 0) {
                    var pt = data.points[0];
                    var x_idx = Math.round(pt.x);
                    var y_idx = Math.round(pt.y);
                    
                    if (y_idx >= 0 && y_idx < __ZDATA_FULL_LENGTH__ && x_idx >= 0 && x_idx < __ZDATA_FULL_WIDTH__) {
                        // For 3D click, we'd need to map 3D indices to 2D indices, but for now we skip or approximate.
                        // Actually, we use the original z_data array in JS for full resolution slices.
                        // Since z_data is now ZDATA3D, cross-section clicks won't map exactly.
                        // We will pass the full z_data as z_data_full just for the click event.
                        var new_x_slice = z_data_full[Math.round(y_idx * (__ZDATA_FULL_LENGTH__ / z_data.length))];
                        var new_y_slice = z_data_full.map(function(row) { return row[Math.round(x_idx * (__ZDATA_FULL_WIDTH__ / z_data[0].length))]; });
                        
                        Plotly.update('plot-xz', { y: [new_x_slice] }, { title: 'X-Z Section (Selected)' }, [1]);
                        Plotly.update('plot-yz', { y: [new_y_slice] }, { title: 'Y-Z Section (Selected)' }, [1]);
                    }
                }
            });
            var z_data_full = __ZDATA__;

            function updateZRange() {
                var zmin = parseFloat(document.getElementById('z-min').value);
                var zmax = parseFloat(document.getElementById('z-max').value);
                if (isNaN(zmin)) zmin = 0;
                if (isNaN(zmax)) zmax = __ZMAX__;
                
                Plotly.relayout('plot', {
                    'scene.zaxis.range': [zmin, zmax],
                    'scene.zaxis.autorange': false
                });
                Plotly.restyle('plot', {
                    cmin: [zmin],
                    cmax: [zmax]
                });
                Plotly.relayout('plot-xz', {
                    'yaxis.range': [zmin, zmax],
                    'yaxis.autorange': false
                });
                Plotly.relayout('plot-yz', {
                    'yaxis.range': [zmin, zmax],
                    'yaxis.autorange': false
                });
            }
            // Force apply range once to ensure 3D scene correctly clips
            updateZRange();
        </script>
    </body>
    </html>
    '''
    html = html_template.replace('__FILENAME__', file_path)\
        .replace('__ZDATA3D__', json.dumps(z_data_3d.tolist()))\
        .replace('__ZDATA__', json.dumps(z_data.tolist()))\
        .replace('__XSLICE__', json.dumps(x_slice))\
        .replace('__YSLICE__', json.dumps(y_slice))\
        .replace('__ZMAX__', str(z_max))\
        .replace('__ZDATA_FULL_LENGTH__', str(len(z_data)))\
        .replace('__ZDATA_FULL_WIDTH__', str(len(z_data[0]) if len(z_data) > 0 else 0))
    print(html)
except Exception as e:
    print(f"<html><body><h3>Error processing image: {str(e)}</h3></body></html>")
"""
    try:
        from fastapi.responses import HTMLResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file,
            cx, cy,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return HTMLResponse(f"<html><body><h3>Error: Script execution failed.</h3><pre>{stderr.decode(errors='replace')}</pre></body></html>", status_code=500)
            
        final_html = stdout.decode(errors='replace').replace('__OPTIONS__', options_html)
        return HTMLResponse(final_html)
    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<html><body><h3>Error: {str(e)}</h3></body></html>", status_code=500)


@router.api_route("/api/starforge/bg_view", methods=["GET", "POST"])
async def starforge_bg_view(request: Request):
    if request.method == "POST":
        form_data = await request.form()
        dir = form_data.get("dir", "")
        session = form_data.get("session", "")
        file = form_data.get("file", "")
        out_dir = form_data.get("out_dir", "")
        cx = form_data.get("cx", "")
        cy = form_data.get("cy", "")
        files_str = form_data.get("files", "")
        use_flat = form_data.get("use_flat", "false").lower() == "true"
        flat_dir = form_data.get("flat_dir", "")
        flat_session = form_data.get("flat_session", "")
        flat_mult = form_data.get("flat_mult", "1.0")
        flat_mult_mode = form_data.get("flat_mult_mode")
        if flat_mult_mode in ["auto_ccr", "auto_fit"]:
            flat_mult = flat_mult_mode
        elif flat_mult_mode == "manual":
            flat_mult = form_data.get("flat_mult_value", "1.0")
    else:
        dir = request.query_params.get("dir", "")
        session = request.query_params.get("session", "")
        file = request.query_params.get("file", "")
        out_dir = request.query_params.get("out_dir", "")
        cx = request.query_params.get("cx", "")
        cy = request.query_params.get("cy", "")
        files_str = request.query_params.get("files", "")
        use_flat = request.query_params.get("use_flat", "false").lower() == "true"
        flat_dir = request.query_params.get("flat_dir", "")
        flat_session = request.query_params.get("flat_session", "")
        flat_mult = request.query_params.get("flat_mult", "1.0")
        flat_mult_mode = request.query_params.get("flat_mult_mode")
        if flat_mult_mode in ["auto_ccr", "auto_fit"]:
            flat_mult = flat_mult_mode
        elif flat_mult_mode == "manual":
            flat_mult = request.query_params.get("flat_mult_value", "1.0")

    abs_dir = os.path.abspath(os.path.expanduser(dir))
    log_file = os.path.join(abs_dir, "shutter_log.json")
    
    file_options = []
    file_map = {}
    bg_map = {}
    bg_medians = {}
    
    allowed_files = set([f.strip() for f in files_str.split(',') if f.strip()]) if files_str else None
    
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                logs = json.load(f)
            for record in logs:
                if not session or record.get("session_id") == session:
                    fname = record.get("record", {}).get("file", {}).get("name")
                    if allowed_files is not None and fname not in allowed_files:
                        continue
                        
                    fpath = record.get("record", {}).get("file", {}).get("path", "")
                    if fname:
                        full_p = os.path.join(fpath if fpath else abs_dir, fname)
                        if fname not in file_map:
                            file_options.append(fname)
                            file_map[fname] = full_p
                        
                        sf = record.get("analysis", {}).get("SF", {})
                        quality = sf.get("quality", {})
                        if "sf_bg_median" in quality:
                            bg_medians[fname] = quality.get("sf_bg_median")

                        bg_img_info = sf.get("bg_image", {})
                        if bg_img_info and isinstance(bg_img_info, dict):
                            bg_path = bg_img_info.get("path", "")
                            bg_name = bg_img_info.get("name", "")
                            if bg_name:
                                bg_full_path = os.path.join(bg_path if bg_path else abs_dir, bg_name)
                                bg_map[fname] = bg_full_path
        except Exception:
            pass
            
    if not file_options and os.path.isdir(abs_dir):
        for f in os.listdir(abs_dir):
            if f.lower().endswith(('.fits', '.fit', '.dng', '.raw', '.cr2', '.nef', '.jpg', '.jpeg', '.png')):
                if f not in file_map:
                    full_p = os.path.join(abs_dir, f)
                    file_options.append(f)
                    file_map[f] = full_p
                    
    if not file_options:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><h3>Error: No background images found in the specified directory/session.</h3></body></html>", status_code=404)

    # Resolve flat file path
    flat_file_path = ""
    if use_flat and flat_dir:
        flat_abs_dir = os.path.abspath(os.path.expanduser(flat_dir))
        search_dirs = [flat_abs_dir, os.path.join(flat_abs_dir, "out")]
        for s_dir in search_dirs:
            if os.path.exists(s_dir):
                try:
                    for f in os.listdir(s_dir):
                        if f.startswith("master_flat_") and f.lower().endswith(('.fits', '.fit')):
                            if not flat_session or f"_{flat_session}" in f:
                                flat_file_path = os.path.join(s_dir, f)
                                break
                except Exception:
                    pass
            if flat_file_path:
                break
    
    # Load flat sessions if flat_dir is provided
    flat_sessions = []
    if flat_dir:
        flat_abs = os.path.abspath(os.path.expanduser(flat_dir))
        flat_log = os.path.join(flat_abs, "shutter_log.json")
        if os.path.exists(flat_log):
            try:
                with open(flat_log, "r") as f:
                    f_logs = json.load(f)
                session_set = set()
                for rec in f_logs:
                    sid = rec.get("session_id")
                    if sid:
                        session_set.add(sid)
                flat_sessions = sorted(list(session_set), reverse=True)
            except Exception:
                pass
    
    flat_sessions_html = ""
    if flat_dir:
        if not flat_sessions:
            flat_sessions_html = '<div class="list-item"><div class="item-label" style="color:var(--text-dim);">No sessions found</div></div>'
        else:
            for sid in flat_sessions:
                selected_cls = "selected" if sid == flat_session else ""
                flat_sessions_html += f'''
                <div class="list-item {selected_cls}" onclick="changeFlatSession('{sid}')">
                    <div class="item-label"><span class="session-name">{sid}</span></div>
                </div>
                '''
        
        status_text = "Applied" if (use_flat and flat_file_path) else ("Not found (No matching master_flat)" if use_flat else "Disabled")
        status_color = "var(--accent-gold)" if (use_flat and flat_file_path) else "var(--text-dim)"
        
        flat_ui_html = f'''
        <div style="padding: 12px; border-top: 1px solid var(--glass-border); background: var(--bg-card); display: flex; flex-direction: column;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h3 style="margin: 0; font-size: 0.8rem; color: var(--accent-gold);">CALIBRATION SETTINGS</h3>
                <button type="button" class="btn-small" onclick="reloadWithParams({{}})" style="padding: 2px 6px; font-size: 0.65rem; background: #333; color: #fff; border: 1px solid #555; border-radius: 3px; cursor: pointer;">Redraw</button>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <label style="display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 0.8rem; cursor: pointer;">
                    <input type="checkbox" id="bg-use-flat" {"checked" if use_flat else ""} onchange="toggleFlat(this.checked)">
                    Flat Calibration
                </label>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 0.7rem; color: var(--text-dim);">Multiplier</span>
                    <input type="number" id="bg-flat-mult" value="{flat_mult if flat_mult not in ['auto_ccr', 'auto_fit'] else '1.0'}" min="0.0" max="3.0" step="0.01" style="width: 60px; padding: 2px 4px; font-size: 0.7rem; background: var(--bg-input); color: #fff; border: 1px solid var(--glass-border); border-radius: 3px;" onchange="reloadWithParams({{}})">
                    <button type="button" class="btn-small" onclick="reloadWithParams({{flat_mult: 'auto_ccr'}})" style="padding: 2px 6px; font-size: 0.65rem; background: #333; color: #fff; border: 1px solid #555; border-radius: 3px; cursor: pointer;" title="Auto adjust to make CCR 0">Auto CCR</button>
                    <button type="button" class="btn-small" onclick="reloadWithParams({{flat_mult: 'auto_fit'}})" style="padding: 2px 6px; font-size: 0.65rem; background: #333; color: #fff; border: 1px solid #555; border-radius: 3px; cursor: pointer;" title="Auto adjust to make Fit 0">Auto Fit</button>
                </div>
            </div>
            <div style="font-size: 0.65rem; color: {status_color}; margin-bottom: 8px; padding-left: 20px;">Status: {status_text}</div>
            
            <div style="font-size: 0.7rem; color: var(--text-dim); margin-bottom: 4px;">Flat Directory</div>
            <div style="font-size: 0.75rem; word-break: break-all; margin-bottom: 8px; font-family: 'JetBrains Mono', monospace;">{flat_dir}</div>
            <div style="font-size: 0.7rem; color: var(--text-dim); margin-bottom: 4px;">Flat Session (optional)</div>
            <div class="list-container" style="max-height: 100px; overflow-y: auto; padding: 0; background: var(--bg-sidebar); border: 1px solid var(--glass-border); border-radius: 6px;">
                {flat_sessions_html}
            </div>
        </div>
        '''
    else:
        flat_ui_html = '''
        <div style="padding: 12px; border-top: 1px solid var(--glass-border); background: var(--bg-card);">
            <div style="font-size: 0.75rem; color: var(--text-dim);">No Flat Directory configured.<br>Please set it in the main GUI.</div>
        </div>
        '''

    if file and file in file_map:
        selected_filename = file
    else:
        selected_filename = file_options[0]

    target_file = file_map[selected_filename]
    bg_image_path = bg_map.get(selected_filename, "")
    
    import urllib.parse
    ext = os.path.splitext(target_file)[1].lower()
    if ext in ['.fit', '.fits']:
        preview_url = f"/api/fits/preview?path={urllib.parse.quote(target_file)}"
    else:
        preview_url = f"/api/logs/image?path={urllib.parse.quote(target_file)}"
        
    preview_html = f"""
    <div style="width: 100%; display: flex; justify-content: center; align-items: center; background: #000; padding: 10px; box-sizing: border-box;">
        <img src="{preview_url}" style="max-width: 100%; max-height: 200px; border-radius: 6px; object-fit: contain; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
    </div>
    """
    
    options_html = '<div class="list-title" style="padding: 6px 10px;">FILES</div>\n'

    for opt in file_options:
        sel = " selected" if opt == selected_filename else ""
        options_html += f"""<div class="list-item{sel}" onclick="changeFile('{opt}')"><div class="file-name">{opt}</div></div>\n"""

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

import os
file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
bg_image_path = sys.argv[4] if len(sys.argv) > 4 else ""
use_flat_str = sys.argv[5] if len(sys.argv) > 5 else "false"
flat_dir_str = sys.argv[6] if len(sys.argv) > 6 else ""
flat_session_str = sys.argv[7] if len(sys.argv) > 7 else ""
flat_file_path_str = sys.argv[8] if len(sys.argv) > 8 else ""
flat_mult_str = sys.argv[9] if len(sys.argv) > 9 else "1.0"

cx = int(cx_str) if cx_str.lstrip("-").isdigit() else -1
cy = int(cy_str) if cy_str.lstrip("-").isdigit() else -1
use_flat = use_flat_str.lower() == "true"
auto_mode = None
try:
    flat_mult = float(flat_mult_str)
except ValueError:
    if flat_mult_str in ["auto_ccr", "auto_fit"]:
        auto_mode = flat_mult_str
    flat_mult = 1.0

def calculate_convexity_metrics(convex_data):
    ccr_pct = 0.0
    curv_val = 0.0
    if convex_data.size > 1:
        ch_c, cw_c = convex_data.shape
        cy_c, cx_c = ch_c // 2, cw_c // 2
        dy, dx = max(1, ch_c // 10), max(1, cw_c // 10)  # 20% x 20% area (offset by 10% from edges)
        
        center_region = convex_data[cy_c-dy:cy_c+dy, cx_c-dx:cx_c+dx]
        # Exclude outer 10% (dy, dx) and take 20% x 20% area (2*dy, 2*dx) from there.
        corner_tl = convex_data[dy:3*dy, dx:3*dx]
        corner_tr = convex_data[dy:3*dy, -3*dx:-dx]
        corner_bl = convex_data[-3*dy:-dy, dx:3*dx]
        corner_br = convex_data[-3*dy:-dy, -3*dx:-dx]
        
        center_med = np.median(center_region) if center_region.size > 0 else 0
        corners = np.concatenate([corner_tl.flatten(), corner_tr.flatten(), corner_bl.flatten(), corner_br.flatten()])
        corner_med = np.median(corners) if corners.size > 0 else 0
        
        if corner_med > 0:
            ccr_pct = (center_med - corner_med) / corner_med * 100.0
            
        h_s, w_s = convex_data.shape
        grid_h_s, grid_w_s = h_s / 16.0, w_s / 16.0
        x_pts, y_pts, z_pts = [], [], []
        for i in range(16):
            for j in range(16):
                r_s = int(i * grid_h_s)
                r_e = int((i+1)*grid_h_s) if i < 15 else h_s
                c_s = int(j * grid_w_s)
                c_e = int((j+1)*grid_w_s) if j < 15 else w_s
                reg = convex_data[r_s:r_e, c_s:c_e]
                if reg.size > 0:
                    y_pts.append(i - 7.5)
                    x_pts.append(j - 7.5)
                    z_pts.append(np.median(reg))
        
        if len(z_pts) > 0:
            x_pts, y_pts, z_pts = np.array(x_pts), np.array(y_pts), np.array(z_pts)
            A_mat = np.c_[x_pts**2, y_pts**2, x_pts, y_pts, np.ones_like(x_pts)]
            try:
                coeffs, _, _, _ = np.linalg.lstsq(A_mat, z_pts, rcond=None)
                A, B = coeffs[0], coeffs[1]
                z_mean = np.mean(z_pts)
                if z_mean > 0:
                    curv_val = -(A + B) * 56.25 / z_mean * 100.0
            except:
                pass
    return ccr_pct, curv_val

def load_img(f_path, target_shape=None):
    if not f_path or not os.path.exists(f_path): return None
    d = None
    try:
        ext = f_path.lower().split('.')[-1]
        if ext in ['fits', 'fit']:
            if has_astropy:
                with fits.open(f_path) as hdul:
                    for hdu in hdul:
                        if hdu.data is not None:
                            d2 = hdu.data
                            if d2.ndim == 3:
                                d = np.mean(d2, axis=0)
                            else:
                                d = d2
                            break
        elif ext in ['dng', 'cr2', 'nef', 'arw', 'raw']:
            if has_rawpy:
                with rawpy.imread(f_path) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=16)
                    d = np.mean(rgb, axis=2)
        elif ext == 'npz':
            with np.load(f_path) as npz:
                d = npz['bg']
        else:
            img = Image.open(f_path).convert('L')
            d = np.array(img)
    except Exception:
        pass
        
    if d is not None and target_shape is not None and d.shape != target_shape:
        import scipy.ndimage
        zoom_y = target_shape[0] / d.shape[0]
        zoom_x = target_shape[1] / d.shape[1]
        
        # Optimize for exact integer downsampling
        if abs(zoom_y - 0.5) < 1e-4 and abs(zoom_x - 0.5) < 1e-4:
            d = d[::2, ::2]
        else:
            d = d.astype(float) # Ensure native endian float for scipy.ndimage
            d = scipy.ndimage.zoom(d, (zoom_y, zoom_x), order=0)
            
    return d

try:
    data = load_img(file_path)
    
    if data is None:
        print("<html><body><h3>Error: Unsupported file format or missing libraries.</h3></body></html>")
        sys.exit(0)
    
    h, w = data.shape
    
    flat_data = None
    flat_mean = 1.0
    if use_flat and flat_file_path_str and os.path.exists(flat_file_path_str):
        flat_data = load_img(flat_file_path_str, target_shape=(h, w))
        if flat_data is not None:
            # Avoid division by zero
            flat_data = np.where(flat_data == 0, 1.0, flat_data)
            flat_mean = np.mean(flat_data)
            flat_factor = flat_mean / flat_data

    bg_data = load_img(bg_image_path, target_shape=(h, w))
    
    if auto_mode and flat_data is not None and bg_data is not None:
        import scipy.optimize
        h_bg, w_bg = bg_data.shape
        scale_2d_bg_opt = max(1, round(w_bg / 160))  # Downsample heavily for fast optimization
        bg_data_down = bg_data[::scale_2d_bg_opt, ::scale_2d_bg_opt].astype(float)
        flat_factor_down = flat_factor[::scale_2d_bg_opt, ::scale_2d_bg_opt]
        
        def objective(m):
            test_z = bg_data_down * (flat_factor_down ** m)
            test_z = np.nan_to_num(test_z, nan=0.0, posinf=0.0, neginf=0.0)
            ccr, fit = calculate_convexity_metrics(test_z)
            return abs(ccr) if auto_mode == "auto_ccr" else abs(fit)
            
        res = scipy.optimize.minimize_scalar(objective, bounds=(0.0, 3.0), method='bounded')
        if res.success:
            flat_mult = float(res.x)

    if flat_data is not None:
        data = data * (flat_factor ** flat_mult)
        if bg_data is not None:
            bg_data = bg_data * (flat_factor ** flat_mult)

    scale_2d = max(1, round(w / 640))
    scale_3d = max(1, round(w / 150))
    
    data_small_2d = data[::scale_2d, ::scale_2d]
    data_small_3d = data[::scale_3d, ::scale_3d]
    
    z_data = data_small_2d.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    z_data_3d = data_small_3d.astype(float)
    z_data_3d = np.nan_to_num(z_data_3d, nan=0.0, posinf=0.0, neginf=0.0)
    
    if bg_data is not None:
        h_bg, w_bg = bg_data.shape
        scale_2d_bg = max(1, round(w_bg / 640))
        scale_3d_bg = max(1, round(w_bg / 150))
        z_data_bg = bg_data[::scale_2d_bg, ::scale_2d_bg].astype(float)
        z_data_bg = np.nan_to_num(z_data_bg, nan=0.0, posinf=0.0, neginf=0.0)
        z_data_3d_bg = bg_data[::scale_3d_bg, ::scale_3d_bg].astype(float)
        z_data_3d_bg = np.nan_to_num(z_data_3d_bg, nan=0.0, posinf=0.0, neginf=0.0)
        
        ch_bg, cw_bg = z_data_bg.shape
        mid_y_bg, mid_x_bg = ch_bg // 2, cw_bg // 2
        x_slice_bg = z_data_bg[mid_y_bg, :].tolist()
        y_slice_bg = z_data_bg[:, mid_x_bg].tolist()
    else:
        z_data_bg = np.array([[0.0]])
        z_data_3d_bg = np.array([[0.0]])
        x_slice_bg = []
        y_slice_bg = []
        
    if bg_data is not None and float(np.max(z_data_bg)) > 0:
        z_max = float(np.max(z_data_bg)) * 1.1
    else:
        z_max = float(np.max(z_data)) * 1.1
        
    if z_max <= 0:
        z_max = 255.0
    
    # Calculate center slices for 2D plots
    ch, cw = z_data.shape
    mid_y, mid_x = ch // 2, cw // 2
    x_slice = z_data[mid_y, :].tolist()
    y_slice = z_data[:, mid_x].tolist()
    
    # Calculate 16x16 medians and MADs
    grid_h, grid_w = h / 16.0, w / 16.0
    medians_16x16 = np.zeros((16, 16))
    mads_16x16 = np.zeros((16, 16))
    for i in range(16):
        for j in range(16):
            r_start = int(i * grid_h)
            r_end = int((i+1)*grid_h) if i < 15 else h
            c_start = int(j * grid_w)
            c_end = int((j+1)*grid_w) if j < 15 else w
            region = data[r_start:r_end, c_start:c_end]
            if region.size > 0:
                med = float(np.median(region))
                medians_16x16[i, j] = med
                mads_16x16[i, j] = float(np.median(np.abs(region - med)))

    # Convexity metrics
    ccr_pct = 0.0
    curv_val = 0.0
    convex_data = z_data_bg if (bg_data is not None and z_data_bg.size > 1) else z_data
    ccr_pct, curv_val = calculate_convexity_metrics(convex_data)

    convexity_html = f"CCR: {ccr_pct:+.1f}% | Fit: {curv_val:+.1f}%"

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Background Image 3D View</title>
        <link rel="stylesheet" href="/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <style>
            .flat-layout-3col {
                display: grid;
                grid-template-columns: 20% 50% 1fr;
                gap: 1rem;
                height: calc(100vh - 120px);
            }
            .col-files { background: var(--bg-sidebar); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-center { position: relative; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-right { display: flex; flex-direction: column; gap: 1rem; height: calc(100vh - 120px); }
            .side-plot { flex: 1; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; overflow: hidden; position: relative; }
            #plot { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
            /* Adjust list-item height and font based on previous request while keeping LOGDATA design */
            .list-item { padding: 8px 8px !important; }
            .file-name { font-size: 0.68rem !important; }
        </style>
        <script>
            function changeFile(filename) {
                var form = document.createElement('form');
                form.method = 'POST';
                form.action = '/api/starforge/bg_view';
                
                var currentUseFlat = document.getElementById('bg-use-flat') ? (document.getElementById('bg-use-flat').checked ? 'true' : 'false') : __USE_FLAT_JS__;
                var currentFlatMult = document.getElementById('bg-flat-mult') ? document.getElementById('bg-flat-mult').value : __FLAT_MULT_JS__;
                
                var params = {
                    'dir': __DIR_JS__,
                    'session': __SESSION_JS__,
                    'out_dir': __OUT_DIR_JS__,
                    'files': __FILES_JS__,
                    'file': filename,
                    'use_flat': currentUseFlat,
                    'flat_dir': __FLAT_DIR_JS__,
                    'flat_session': __FLAT_SESSION_JS__,
                    'flat_mult': currentFlatMult
                };
                
                for (var key in params) {
                    if (params[key] !== '' && params[key] !== null) {
                        var input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = key;
                        input.value = params[key];
                        form.appendChild(input);
                    }
                }
                document.body.appendChild(form);
                form.submit();
            }
            
            function reloadWithParams(updates) {
                var form = document.createElement('form');
                form.method = 'POST';
                form.action = '/api/starforge/bg_view';
                
                var currentUseFlat = document.getElementById('bg-use-flat') ? (document.getElementById('bg-use-flat').checked ? 'true' : 'false') : __USE_FLAT_JS__;
                var currentFlatMult = document.getElementById('bg-flat-mult') ? document.getElementById('bg-flat-mult').value : __FLAT_MULT_JS__;
                
                var params = {
                    'dir': __DIR_JS__,
                    'session': __SESSION_JS__,
                    'out_dir': __OUT_DIR_JS__,
                    'files': __FILES_JS__,
                    'file': __FILE_JS__,
                    'use_flat': currentUseFlat,
                    'flat_dir': __FLAT_DIR_JS__,
                    'flat_session': __FLAT_SESSION_JS__,
                    'flat_mult': currentFlatMult
                };
                
                for (var key in updates) {
                    params[key] = updates[key];
                }
                
                for (var key in params) {
                    if (params[key] !== '' && params[key] !== null) {
                        var input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = key;
                        input.value = params[key];
                        form.appendChild(input);
                    }
                }
                document.body.appendChild(form);
                form.submit();
            }
            
            function toggleFlat(checked) {
                reloadWithParams({'use_flat': checked ? 'true' : 'false'});
            }
            
            function changeFlatSession(sid) {
                reloadWithParams({'flat_session': sid});
            }
        </script>
    </head>
    <body>
        <div class="container" style="max-width: 100%;">
            <header>
                <div class="header-main">
                    <h1>OrionFieldStack <span class="v-tag">Background Viewer</span></h1>
                </div>
            </header>
            
            <main>
                <div class="flat-layout-3col">
                    <aside class="col-files">
                        __PREVIEW__
                        <div class="list-container" style="padding: 0; display: flex; flex-direction: column; flex: 1; overflow-y: auto;">
                            __OPTIONS__
                        </div>
                        __FLAT_UI__
                    </aside>
                    <div class="col-center">
                        <!-- NEW BAR CHART -->
                        <div style="position: relative; width: 100%; height: 120px; border-bottom: 1px solid var(--glass-border);">
                            <div id="bg-median-chart" style="width: 100%; height: 100%;"></div>
                            <div style="position: absolute; top: 8px; right: 8px; z-index: 10; display: flex; gap: 6px;">
                                <button onclick="setChartFullScale()" style="padding: 2px 8px; background: #222; color: #eee; border: 1px solid #555; border-radius: 4px; cursor: pointer; font-size: 0.7rem;">Full</button>
                                <button onclick="setChartZoomScale()" style="padding: 2px 8px; background: #222; color: #eee; border: 1px solid #555; border-radius: 4px; cursor: pointer; font-size: 0.7rem;">Zoom</button>
                            </div>
                        </div>
                        <!-- Z-AXIS CONTROL BAR -->
                        <div style="display: flex; align-items: center; gap: 12px; background: var(--bg-card); padding: 8px 12px; border-bottom: 1px solid var(--glass-border);">
                            <span style="font-size: 0.85rem; color: var(--accent-gold); font-weight: bold;">Z-AXIS</span>
                            <label style="font-size: 0.8rem; color: var(--text-dim);">Min:</label>
                            <input type="number" id="z-min" value="0" step="any" style="width: 100px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                            <label style="font-size: 0.8rem; color: var(--text-dim);">Max:</label>
                            <input type="number" id="z-max" value="__ZMAX__" step="any" style="width: 100px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                            <button onclick="setRawFullScale()" style="padding: 4px 10px; background: #222; color: #eee; border: 1px solid #555; border-radius: 4px; cursor: pointer; font-size: 0.8rem;">RAW Full Scale</button>
                            <button onclick="setBgFullScale()" style="padding: 4px 10px; background: #222; color: #eee; border: 1px solid #555; border-radius: 4px; cursor: pointer; font-size: 0.8rem;">BG Full Scale</button>
                        </div>
                        <div style="flex: 1; display: flex; flex-direction: row; gap: 10px; position: relative;">
                            <div style="flex: 1; position: relative; border-right: 1px solid var(--glass-border);">
                                <div style="position: absolute; top: 10px; left: 10px; z-index: 10; background: rgba(0,0,0,0.6); padding: 4px 8px; border-radius: 4px; color: var(--accent-gold); font-weight: bold; font-size: 0.8rem;">DNG / RAW</div>
                                <div id="plot" style="width: 100%; height: 100%;"></div>
                            </div>
                            <div style="flex: 1; position: relative;">
                                <div style="position: absolute; top: 10px; left: 10px; z-index: 10; background: rgba(0,0,0,0.6); padding: 4px 8px; border-radius: 4px; color: var(--accent-gold); font-weight: bold; font-size: 0.8rem; display: flex; flex-direction: column; gap: 4px;">
                                    <span>Background Image</span>
                                    <span style="font-size: 0.7rem; color: #fff; background: #333; padding: 2px 6px; border-radius: 3px; white-space: nowrap;">Convexity: __CONVEXITY_HTML__</span>
                                </div>
                                <div id="plot-bg" style="width: 100%; height: 100%;"></div>
                            </div>
                        </div>
                        <div style="height: 35%; display: flex; gap: 10px; padding: 10px; border-top: 1px solid var(--glass-border); background: var(--bg-card);">
                            <div style="flex: 1; display: flex; flex-direction: column;">
                                <h3 style="margin: 0 0 8px 0; font-size: 0.8rem;">16x16 MEDIAN HEATMAP</h3>
                                <div id="median-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                            </div>
                            <div style="flex: 1; display: flex; flex-direction: column;">
                                <h3 style="margin: 0 0 8px 0; font-size: 0.8rem;">16x16 MAD HEATMAP (Median Absolute Deviation)</h3>
                                <div id="mad-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                            </div>
                        </div>
                    </div>
                    <div class="col-right">
                        <div id="plot-xz" class="side-plot"></div>
                        <div id="plot-yz" class="side-plot"></div>
                    </div>
                </div>
            </main>
        </div>
        <script>
            var z_data = __ZDATA3D__;
            var x_slice = __XSLICE__;
            var y_slice = __YSLICE__;
            var x_slice_bg = __XSLICE_BG__;
            var y_slice_bg = __YSLICE_BG__;
 
            // 3D Plot
            var data3d = [{
                z: z_data,
                type: 'surface',
                colorscale: 'Viridis',
                cmin: 0,
                cmax: __ZMAX__,
                showscale: false
            }];
            var aspect_x = z_data[0].length / Math.max(z_data.length, z_data[0].length);
            var aspect_y = z_data.length / Math.max(z_data.length, z_data[0].length);

            // Bar Chart for Background Medians
            var filenames = __FILENAMES__;
            var bgMedians = __BGMEDIANS__;
            var selectedFilename = '__SELECTED_FILENAME__';
            var colors = filenames.map(function(f) { return f === selectedFilename ? '#ff4757' : '#3a86ff'; });
            
            var barData = [{
                x: filenames,
                y: bgMedians,
                type: 'bar',
                marker: { color: colors }
            }];
            var barLayout = {
                title: { text: 'Background Median', font: {size: 12} },
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff', size: 10},
                margin: {t: 20, b: 20, l: 40, r: 20},
                xaxis: { showticklabels: false },
                yaxis: { title: 'Median', tickfont: {size: 9} }
            };
            Plotly.newPlot('bg-median-chart', barData, barLayout, {responsive: true});
            
            document.getElementById('bg-median-chart').on('plotly_click', function(data) {
                if (data.points && data.points.length > 0) {
                    var clickedFilename = data.points[0].x;
                    changeFile(clickedFilename);
                }
            });

            function setChartFullScale() {
                if (bgMedians && bgMedians.length > 0) {
                    var maxVal = Math.max.apply(null, bgMedians);
                    Plotly.relayout('bg-median-chart', {
                        'yaxis.range': [0, maxVal * 1.05],
                        'yaxis.autorange': false
                    });
                }
            }

            function setChartZoomScale() {
                if (bgMedians && bgMedians.length > 0) {
                    var minVal = Math.min.apply(null, bgMedians);
                    var maxVal = Math.max.apply(null, bgMedians);
                    var padding = (maxVal - minVal) * 0.1;
                    if (padding === 0) padding = minVal * 0.1;
                    if (padding === 0) padding = 1;
                    Plotly.relayout('bg-median-chart', {
                        'yaxis.range': [Math.max(0, minVal - padding), maxVal + padding],
                        'yaxis.autorange': false
                    });
                }
            }

            var layout3d = {
                autosize: true,
                scene: {
                    xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                    yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true, autorange: 'reversed' },
                    zaxis: { title: 'Luminance', range: [0, __ZMAX__], autorange: false },
                    aspectmode: 'manual',
                    aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                    camera: {
                        eye: {x: -1.5, y: -1.5, z: 1.2}
                    }
                },
                margin: { l: 0, r: 0, b: 0, t: 0 },
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212'
            };
            Plotly.newPlot('plot', data3d, layout3d, {responsive: true});

            var z_data_bg = __ZDATA3D_BG__;
            if (z_data_bg && z_data_bg.length > 0 && z_data_bg[0].length > 1) {
                var data3d_bg = [{
                    z: z_data_bg,
                    type: 'surface',
                    colorscale: 'Viridis',
                    cmin: 0,
                    cmax: __ZMAX__,
                    showscale: false
                }];
                var aspect_x_bg = z_data_bg[0].length / Math.max(z_data_bg.length, z_data_bg[0].length);
                var aspect_y_bg = z_data_bg.length / Math.max(z_data_bg.length, z_data_bg[0].length);

                var layout3d_bg = {
                    autosize: true,
                    scene: {
                        xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                        yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true, autorange: 'reversed' },
                        zaxis: { title: 'Luminance', range: [0, __ZMAX__], autorange: false },
                        aspectmode: 'manual',
                        aspectratio: { x: aspect_x_bg, y: aspect_y_bg, z: 0.25 },
                        camera: {
                            eye: {x: -1.5, y: -1.5, z: 1.2}
                        }
                    },
                    margin: { l: 0, r: 0, b: 0, t: 0 },
                    paper_bgcolor: '#121212',
                    plot_bgcolor: '#121212'
                };
                Plotly.newPlot('plot-bg', data3d_bg, layout3d_bg, {responsive: true});
                
                // Sync 3D plots in real-time
                var plotEl = document.getElementById('plot');
                var plotBgEl = document.getElementById('plot-bg');
                
                var activePlot = null;
                var lastCamString = "";
                var isRelayouting = false;
                
                plotEl.addEventListener('mouseenter', function() { activePlot = plotEl; });
                plotBgEl.addEventListener('mouseenter', function() { activePlot = plotBgEl; });
                plotEl.addEventListener('mouseleave', function() { if(activePlot === plotEl) activePlot = null; });
                plotBgEl.addEventListener('mouseleave', function() { if(activePlot === plotBgEl) activePlot = null; });
                
                function syncCameras() {
                    if (activePlot && !isRelayouting) {
                        var source = activePlot;
                        var target = (activePlot === plotEl) ? plotBgEl : plotEl;
                        
                        if (source._fullLayout && source._fullLayout.scene) {
                            var cam = null;
                            if (source._fullLayout.scene._scene && typeof source._fullLayout.scene._scene.getCamera === 'function') {
                                cam = source._fullLayout.scene._scene.getCamera();
                            } else if (typeof source._fullLayout.scene.getCamera === 'function') {
                                cam = source._fullLayout.scene.getCamera();
                            } else {
                                cam = source._fullLayout.scene.camera;
                            }
                            
                            if (cam) {
                                // Extract only eye, center, up to avoid circular references
                                var cleanCam = {
                                    center: cam.center || {x:0, y:0, z:0},
                                    eye: cam.eye || {x:1.25, y:1.25, z:1.25},
                                    up: cam.up || {x:0, y:0, z:1}
                                };
                                var camString = JSON.stringify(cleanCam);
                                if (camString !== lastCamString) {
                                    isRelayouting = true;
                                    lastCamString = camString;
                                    Plotly.relayout(target, {'scene.camera': cleanCam})
                                        .then(function() { isRelayouting = false; })
                                        .catch(function() { isRelayouting = false; });
                                }
                            }
                        }
                    }
                    requestAnimationFrame(syncCameras);
                }
                requestAnimationFrame(syncCameras);
            } else {
                document.getElementById('plot-bg').innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);">No Background Image</div>';
            }
            // X-Z Section
            var dataXZ = [
                { y: x_slice, type: 'scatter', mode: 'lines', name: 'DNG Ctr', line: {color: '#00ff88', dash: 'dash'} },
                { y: x_slice, type: 'scatter', mode: 'lines', name: 'DNG Sel', line: {color: '#ffffff'} },
                { y: x_slice_bg, type: 'scatter', mode: 'lines', name: 'BG Ctr', line: {color: '#aaaaaa', dash: 'dash'} },
                { y: x_slice_bg, type: 'scatter', mode: 'lines', name: 'BG Sel', line: {color: '#88aaff'} }
            ];
            var layoutXZ = {
                title: 'X-Z Section (Center & Selected)',
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff'},
                margin: {t: 40, b: 40, l: 40, r: 20},
                xaxis: { title: 'X', showgrid: true, gridcolor: '#333' },
                yaxis: { title: 'Luminance', showgrid: true, gridcolor: '#333', range: [0, __ZMAX__] },
                showlegend: true,
                legend: { x: 1, xanchor: 'right', y: 1, bgcolor: 'rgba(0,0,0,0)', font: {size: 10} }
            };
            Plotly.newPlot('plot-xz', dataXZ, layoutXZ, {responsive: true});

            // Y-Z Section
            var dataYZ = [
                { y: y_slice, type: 'scatter', mode: 'lines', name: 'DNG Ctr', line: {color: '#ff0088', dash: 'dash'} },
                { y: y_slice, type: 'scatter', mode: 'lines', name: 'DNG Sel', line: {color: '#ffffff'} },
                { y: y_slice_bg, type: 'scatter', mode: 'lines', name: 'BG Ctr', line: {color: '#aaaaaa', dash: 'dash'} },
                { y: y_slice_bg, type: 'scatter', mode: 'lines', name: 'BG Sel', line: {color: '#ffaa88'} }
            ];
            var layoutYZ = {
                title: 'Y-Z Section (Center & Selected)',
                paper_bgcolor: '#121212',
                plot_bgcolor: '#121212',
                font: {color: '#fff'},
                margin: {t: 40, b: 40, l: 40, r: 20},
                xaxis: { title: 'Y', showgrid: true, gridcolor: '#333' },
                yaxis: { title: 'Luminance', showgrid: true, gridcolor: '#333', range: [0, __ZMAX__] },
                showlegend: true,
                legend: { x: 1, xanchor: 'right', y: 1, bgcolor: 'rgba(0,0,0,0)', font: {size: 10} }
            };
            Plotly.newPlot('plot-yz', dataYZ, layoutYZ, {responsive: true});

            // Add click event for 3D plot to update selected cross-sections
            var plotDiv = document.getElementById('plot');
            var plotBgDiv = document.getElementById('plot-bg');
            var z_data_full = __ZDATA__;
            var z_data_bg_full = __ZDATABG__;
            
            function updateCrossSections(pt, source_len, source_width) {
                var x_idx = Math.round(pt.x);
                var y_idx = Math.round(pt.y);
                
                // For DNG
                if (y_idx >= 0 && y_idx < source_len && x_idx >= 0 && x_idx < source_width) {
                    var dng_y = Math.round(y_idx * (__ZDATA_FULL_LENGTH__ / source_len));
                    var dng_x = Math.round(x_idx * (__ZDATA_FULL_WIDTH__ / source_width));
                    if (dng_y >= 0 && dng_y < z_data_full.length) {
                        var new_x_slice = z_data_full[dng_y];
                        var new_y_slice = z_data_full.map(function(row) { return row[dng_x]; });
                        Plotly.update('plot-xz', { y: [new_x_slice] }, {}, [1]);
                        Plotly.update('plot-yz', { y: [new_y_slice] }, {}, [1]);
                    }
                }
                
                // For BG
                if (z_data_bg_full && z_data_bg_full.length > 0) {
                    var bg_h = z_data_bg_full.length;
                    var bg_w = z_data_bg_full[0].length;
                    var bg_y_idx = Math.round(y_idx * (bg_h / source_len));
                    var bg_x_idx = Math.round(x_idx * (bg_w / source_width));
                    if (bg_y_idx >= 0 && bg_y_idx < bg_h && bg_x_idx >= 0 && bg_x_idx < bg_w) {
                        var new_x_slice_bg = z_data_bg_full[bg_y_idx];
                        var new_y_slice_bg = z_data_bg_full.map(function(row) { return row[bg_x_idx]; });
                        Plotly.update('plot-xz', { y: [new_x_slice_bg] }, {}, [3]);
                        Plotly.update('plot-yz', { y: [new_y_slice_bg] }, {}, [3]);
                    }
                }
            }

            if (plotDiv) {
                plotDiv.on('plotly_click', function(data) {
                    if (data.points && data.points.length > 0) updateCrossSections(data.points[0], z_data.length, z_data[0].length);
                });
            }
            if (plotBgDiv) {
                plotBgDiv.on('plotly_click', function(data) {
                    if (data.points && data.points.length > 0) updateCrossSections(data.points[0], z_data_bg.length, z_data_bg[0].length);
                });
            }

            // Populate 16x16 Grid
            var medians = __MEDIANS_16X16__;
            var max_med = -Infinity;
            var min_med = Infinity;
            for(var i=0; i<16; i++) {
                for(var j=0; j<16; j++) {
                    if (medians[i][j] > max_med) max_med = medians[i][j];
                    if (medians[i][j] < min_med) min_med = medians[i][j];
                }
            }
            var gridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = medians[i][j];
                    var norm = max_med > min_med ? (val - min_med) / (max_med - min_med) : 0;
                    var r = Math.round(30 + norm * 225);
                    var g = Math.round(30 + norm * 21);
                    var b = Math.round(30 + norm * 72);
                    gridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" title="Row ${i+1}, Col ${j+1}: ${val}">${Number(val.toPrecision(3))}</div>`;
                }
            }
            document.getElementById('median-grid').innerHTML = gridHtml;

            // Populate 16x16 MAD Grid
            var mads = __MADS_16X16__;
            var max_mad = -Infinity;
            var min_mad = Infinity;
            for(var i=0; i<16; i++) {
                for(var j=0; j<16; j++) {
                    if (mads[i][j] > max_mad) max_mad = mads[i][j];
                    if (mads[i][j] < min_mad) min_mad = mads[i][j];
                }
            }
            var madGridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = mads[i][j];
                    var norm = max_mad > min_mad ? (val - min_mad) / (max_mad - min_mad) : 0;
                    var r = Math.round(30 + norm * 123);
                    var g = Math.round(30 + norm * 21);
                    var b = Math.round(30 + norm * 225);
                    madGridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" title="Row ${i+1}, Col ${j+1}: ${val}">${Number(val.toPrecision(3))}</div>`;
                }
            }
            document.getElementById('mad-grid').innerHTML = madGridHtml;

            function updateZRange() {
                var zmin = parseFloat(document.getElementById('z-min').value);
                var zmax = parseFloat(document.getElementById('z-max').value);
                if (isNaN(zmin)) zmin = 0;
                if (isNaN(zmax)) zmax = __ZMAX__;
                
                Plotly.relayout('plot', {
                    'scene.zaxis.range': [zmin, zmax],
                    'scene.zaxis.autorange': false
                });
                Plotly.restyle('plot', {
                    cmin: [zmin],
                    cmax: [zmax]
                });
                
                var bg_plot_div = document.getElementById('plot-bg');
                if (bg_plot_div && bg_plot_div.data) {
                    Plotly.relayout('plot-bg', {
                        'scene.zaxis.range': [zmin, zmax],
                        'scene.zaxis.autorange': false
                    });
                    Plotly.restyle('plot-bg', {
                        cmin: [zmin],
                        cmax: [zmax]
                    });
                }
                Plotly.relayout('plot-xz', {
                    'yaxis.range': [zmin, zmax],
                    'yaxis.autorange': false
                });
                Plotly.relayout('plot-yz', {
                    'yaxis.range': [zmin, zmax],
                    'yaxis.autorange': false
                });
            }
            
            function roundToTwoSigFigs(num) {
                if (num === 0) return 0;
                return Number(num.toPrecision(2));
            }
            
            function getMatrixMax(matrix) {
                if (!matrix || matrix.length === 0) return 0;
                var maxVal = -Infinity;
                for (var i = 0; i < matrix.length; i++) {
                    for (var j = 0; j < matrix[i].length; j++) {
                        if (matrix[i][j] > maxVal) maxVal = matrix[i][j];
                    }
                }
                return maxVal;
            }
            
            function setRawFullScale() {
                if (typeof z_data !== 'undefined' && z_data && z_data.length > 0) {
                    var rawMax = getMatrixMax(z_data);
                    var newMax = roundToTwoSigFigs(rawMax * 1.1);
                    document.getElementById('z-max').value = newMax;
                    updateZRange();
                }
            }
            
            function setBgFullScale() {
                if (typeof z_data_bg !== 'undefined' && z_data_bg && z_data_bg.length > 0) {
                    var bgMax = getMatrixMax(z_data_bg);
                    var newMax = roundToTwoSigFigs(bgMax * 1.1);
                    document.getElementById('z-max').value = newMax;
                    updateZRange();
                }
            }
            
            // Force apply range once to ensure 3D scene correctly clips
            updateZRange();
            
            var optimizedMult = __OPTIMIZED_FLAT_MULT__;
            if (optimizedMult !== null) {
                var multInput = document.getElementById('bg-flat-mult');
                if (multInput) {
                    multInput.value = optimizedMult.toFixed(3);
                }
            }
        </script>
    </body>
    </html>
    '''
    html = html_template.replace('__FILENAME__', file_path)\
        .replace('__OPTIMIZED_FLAT_MULT__', str(flat_mult) if auto_mode else "null")\
        .replace('__ZDATA3D__', json.dumps(z_data_3d.tolist()))\
        .replace('__ZDATA3D_BG__', json.dumps(z_data_3d_bg.tolist()))\
        .replace('__ZDATA__', json.dumps(z_data.tolist()))\
        .replace('__XSLICE__', json.dumps(x_slice))\
        .replace('__YSLICE__', json.dumps(y_slice))\
        .replace('__XSLICE_BG__', json.dumps(x_slice_bg))\
        .replace('__YSLICE_BG__', json.dumps(y_slice_bg))\
        .replace('__ZDATABG__', json.dumps(z_data_bg.tolist()))\
        .replace('__ZMAX__', str(z_max))\
        .replace('__ZDATA_FULL_LENGTH__', str(len(z_data)))\
        .replace('__ZDATA_FULL_WIDTH__', str(len(z_data[0]) if len(z_data) > 0 else 0))\
        .replace('__MEDIANS_16X16__', json.dumps(medians_16x16.tolist()))\
        .replace('__MADS_16X16__', json.dumps(mads_16x16.tolist()))\
        .replace('__CONVEXITY_HTML__', convexity_html)
    print(html)
except Exception as e:
    print(f"<html><body><h3>Error processing image: {str(e)}</h3></body></html>")
"""
    try:
        from fastapi.responses import HTMLResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file,
            cx, cy, bg_image_path, str(use_flat).lower(), flat_dir, flat_session, flat_file_path, str(flat_mult),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return HTMLResponse(f"<html><body><h3>Error: Script execution failed.</h3><pre>{stderr.decode(errors='replace')}</pre></body></html>", status_code=500)
            
        chart_filenames = file_options
        chart_medians = [bg_medians.get(fname, 0) for fname in file_options]
        
        final_html = stdout.decode(errors='replace')\
            .replace('__PREVIEW__', preview_html)\
            .replace('__OPTIONS__', options_html)\
            .replace('__FLAT_UI__', flat_ui_html)\
            .replace('__FILENAMES__', json.dumps(chart_filenames))\
            .replace('__BGMEDIANS__', json.dumps(chart_medians))\
            .replace('__SELECTED_FILENAME__', selected_filename)\
            .replace('__DIR_JS__', json.dumps(dir))\
            .replace('__SESSION_JS__', json.dumps(session))\
            .replace('__OUT_DIR_JS__', json.dumps(out_dir))\
            .replace('__FILES_JS__', json.dumps(files_str))\
            .replace('__FILE_JS__', json.dumps(selected_filename))\
            .replace('__USE_FLAT_JS__', json.dumps('true' if use_flat else 'false'))\
            .replace('__FLAT_DIR_JS__', json.dumps(flat_dir))\
            .replace('__FLAT_SESSION_JS__', json.dumps(flat_session))\
            .replace('__FLAT_MULT_JS__', json.dumps(flat_mult))
        return HTMLResponse(final_html)
    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<html><body><h3>Error: {str(e)}</h3></body></html>", status_code=500)





def get_dark_target_file(dir: str, session: str, file: str, out_dir: str):
    abs_dir = os.path.abspath(os.path.expanduser(dir))
    log_file = os.path.join(abs_dir, "shutter_log.json")
    
    file_options = []
    file_map = {}
    
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                logs = json.load(f)
            for record in logs:
                if not session or record.get("session_id") == session:
                    fname = record.get("record", {}).get("file", {}).get("name")
                    fpath = record.get("record", {}).get("file", {}).get("path", "")
                    if fname:
                        full_p = os.path.join(fpath if fpath else abs_dir, fname)
                        if fname not in file_map:
                            file_options.append(fname)
                            file_map[fname] = full_p
        except Exception:
            pass
            
    if not file_options and os.path.isdir(abs_dir):
        for f in os.listdir(abs_dir):
            if f.lower().endswith(('.fits', '.fit', '.dng', '.raw', '.cr2', '.nef', '.jpg', '.jpeg', '.png')):
                if f not in file_map:
                    full_p = os.path.join(abs_dir, f)
                    file_options.append(f)
                    file_map[f] = full_p
                    
    stacked_files = []
    search_dirs = []
    if out_dir:
        search_dirs.append(os.path.abspath(os.path.expanduser(out_dir)))
    search_dirs.append(abs_dir)
    
    # Remove duplicates
    search_dirs = list(dict.fromkeys(search_dirs))
    
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            prefix = "master_dark_"
            try:
                for f in os.listdir(s_dir):
                    if f.startswith(prefix) and f.lower().endswith(('.fits', '.fit')):
                        if not session or f"_{session}" in f:
                            if f not in stacked_files:
                                stacked_files.append(f)
                                if f not in file_map:
                                    file_map[f] = os.path.join(s_dir, f)
            except Exception:
                pass

    if file and file in file_map:
        selected_filename = file
    elif stacked_files:
        selected_filename = stacked_files[0]
    elif file_options:
        selected_filename = file_options[0]
    else:
        return None, None, None, None, None

    target_file = file_map[selected_filename]
    return target_file, selected_filename, file_options, stacked_files, abs_dir


@router.get("/api/starforge/dark_crop_3d")
async def starforge_dark_crop_3d(dir: str, session: str = "", file: str = "", out_dir: str = "", cx: str = "", cy: str = "", grid_row: str = "", grid_col: str = "", k_val: str = "1000"):
    target_file, _, _, _, _ = get_dark_target_file(dir, session, file, out_dir)
    if not target_file:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "No dark images found"}, status_code=404)

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
grid_row_str = sys.argv[4] if len(sys.argv) > 4 else "-1"
grid_col_str = sys.argv[5] if len(sys.argv) > 5 else "-1"
k_val_str = sys.argv[6] if len(sys.argv) > 6 else "1000"

cx = int(float(cx_str)) if cx_str.strip() and cx_str.replace('.','',1).lstrip("-").isdigit() else -1
cy = int(float(cy_str)) if cy_str.strip() and cy_str.replace('.','',1).lstrip("-").isdigit() else -1
grid_row = int(grid_row_str) if grid_row_str.lstrip("-").isdigit() else -1
grid_col = int(grid_col_str) if grid_col_str.lstrip("-").isdigit() else -1
k_val = float(k_val_str) if k_val_str.replace('.', '', 1).isdigit() else 1000.0

try:
    ext = file_path.lower().split('.')[-1]
    data = None
    if ext in ['fits', 'fit']:
        if has_astropy:
            with fits.open(file_path) as hdul:
                for hdu in hdul:
                    if hdu.data is not None:
                        d = hdu.data
                        if d.ndim == 3 and d.shape[0] in [3, 4]:
                            data = np.mean(d, axis=0)
                        elif d.ndim == 3 and d.shape[2] in [3, 4]:
                            data = np.mean(d, axis=2)
                        else:
                            data = d
                        break
    elif ext in ['dng', 'raw', 'cr2', 'nef']:
        if has_rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=False, no_auto_bright=True, output_bps=16)
                data = np.mean(rgb, axis=2)
    else:
        img = Image.open(file_path).convert('L')
        data = np.array(img)

    if data is None:
        print(json.dumps({"error": "Unsupported file format"}))
        sys.exit(0)

    h, w = data.shape
    
    if grid_row >= 0 and grid_col >= 0:
        grid_h, grid_w = h / 16.0, w / 16.0
        start_y = int(grid_row * grid_h)
        end_y = int((grid_row+1)*grid_h) if grid_row < 15 else h
        start_x = int(grid_col * grid_w)
        end_x = int((grid_col+1)*grid_w) if grid_col < 15 else w
        crop_h = end_y - start_y
        crop_w = end_x - start_x
    else:
        crop_h = min(300, h)
        crop_w = min(300, w)
        if cx >= 0 and cy >= 0:
            start_x = max(0, min(cx - crop_w // 2, w - crop_w))
            start_y = max(0, min(cy - crop_h // 2, h - crop_h))
        else:
            start_x = (w - crop_w) // 2
            start_y = (h - crop_h) // 2
            
    data_crop = data[start_y:start_y+crop_h, start_x:start_x+crop_w]
    z_data = data_crop.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    crop_med = float(np.median(z_data)) if z_data.size > 0 else 0
    crop_mad = float(np.median(np.abs(z_data - crop_med))) if z_data.size > 0 else 0
    z_max = (crop_med + k_val * crop_mad) * 2.0 if z_data.size > 0 else 255.0
    
    print(json.dumps({"z_data": z_data.tolist(), "z_max": z_max}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
"""
    try:
        from fastapi.responses import JSONResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file,
            cx, cy, grid_row, grid_col, k_val,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return JSONResponse({"error": "Script execution failed", "stderr": stderr.decode(errors='replace')}, status_code=500)
            
        return JSONResponse(json.loads(stdout.decode(errors='replace')))
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=500)



@router.get("/api/starforge/dark_view")
async def starforge_dark_view(dir: str, session: str = "", file: str = "", out_dir: str = "", cx: str = "", cy: str = "", grid_row: str = "", grid_col: str = "", k_val: str = "1000", plot3d: str = "0", use_global_mad: str = "1"):
    # If no custom crop is specified and no grid is specified, default to Grid 0,0
    if not cx and not cy and not grid_row and not grid_col:
        grid_row = "0"
        grid_col = "0"
    if not grid_row:
        grid_row = "-1"
    if not grid_col:
        grid_col = "-1"

    target_file, selected_filename, file_options, stacked_files, abs_dir = get_dark_target_file(dir, session, file, out_dir)
    
    if not target_file:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<html><body><h3>Error: No dark images found in the specified directory/session.</h3></body></html>", status_code=404)

    options_html = ""
    if stacked_files:
        options_html += '<h3 style="padding: 6px 10px; margin: 0;">STACKED FILE</h3>\n'
        for sf in stacked_files:
            sel = " selected" if sf == selected_filename else ""
            options_html += f'''<div class="list-item{sel}" onclick="changeFile('{sf}')"><div class="file-name" style="color: var(--accent-gold); font-weight: 600;">{sf}</div></div>\n'''
        options_html += '<h3 style="margin-top: 8px; border-top: 1px solid var(--glass-border); padding: 12px 10px 0 10px;">FILES</h3>\n'
    else:
        options_html += '<h3 style="padding: 6px 10px; margin: 0;">FILES</h3>\n'

    for opt in file_options:
        sel = " selected" if opt == selected_filename else ""
        options_html += f'''<div class="list-item{sel}" onclick="changeFile('{opt}')"><div class="file-name">{opt}</div></div>\n'''

    python_code = """
import sys
import numpy as np
import json
from PIL import Image

try:
    from astropy.io import fits
    has_astropy = True
except ImportError:
    has_astropy = False

try:
    import rawpy
    has_rawpy = True
except ImportError:
    has_rawpy = False

try:
    from scipy.ndimage import label
    has_scipy = True
except ImportError:
    has_scipy = False

file_path = sys.argv[1]
cx_str = sys.argv[2] if len(sys.argv) > 2 else ""
cy_str = sys.argv[3] if len(sys.argv) > 3 else ""
grid_row_str = sys.argv[4] if len(sys.argv) > 4 else "-1"
grid_col_str = sys.argv[5] if len(sys.argv) > 5 else "-1"
k_val_str = sys.argv[6] if len(sys.argv) > 6 else "1000"
plot3d_str = sys.argv[7] if len(sys.argv) > 7 else "0"
use_global_mad_str = sys.argv[8] if len(sys.argv) > 8 else "1"

cx = int(float(cx_str)) if cx_str.strip() and cx_str.replace('.','',1).lstrip("-").isdigit() else -1
cy = int(float(cy_str)) if cy_str.strip() and cy_str.replace('.','',1).lstrip("-").isdigit() else -1
grid_row = int(grid_row_str) if grid_row_str.lstrip("-").isdigit() else -1
grid_col = int(grid_col_str) if grid_col_str.lstrip("-").isdigit() else -1
k_val = float(k_val_str) if k_val_str.replace('.', '', 1).isdigit() else 1000.0
plot3d = int(plot3d_str) if plot3d_str.isdigit() else 0
use_global_mad = int(use_global_mad_str) if use_global_mad_str.isdigit() else 1
data = None

try:
    ext = file_path.lower().split('.')[-1]
    if ext in ['fits', 'fit']:
        if has_astropy:
            with fits.open(file_path) as hdul:
                for hdu in hdul:
                    if hdu.data is not None:
                        d = hdu.data
                        if d.ndim == 3:
                            data = np.mean(d, axis=0)
                        else:
                            data = d
                        break
    elif ext in ['dng', 'cr2', 'nef', 'arw', 'raw']:
        if has_rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=False, no_auto_bright=True, output_bps=16)
                data = np.mean(rgb, axis=2)
    else:
        img = Image.open(file_path).convert('L')
        data = np.array(img)

    if data is None:
        print("<html><body><h3>Error: Unsupported file format or missing libraries.</h3></body></html>")
        sys.exit(0)

    h, w = data.shape
    
    # Extract grid partition if grid coordinates provided
    if grid_row >= 0 and grid_col >= 0:
        grid_h, grid_w = h / 16.0, w / 16.0
        start_y = int(grid_row * grid_h)
        end_y = int((grid_row+1)*grid_h) if grid_row < 15 else h
        start_x = int(grid_col * grid_w)
        end_x = int((grid_col+1)*grid_w) if grid_col < 15 else w
        crop_h = end_y - start_y
        crop_w = end_x - start_x
        actual_cx = start_x + crop_w // 2
        actual_cy = start_y + crop_h // 2
    else:
        crop_h = min(300, h)
        crop_w = min(300, w)
        if cx >= 0 and cy >= 0:
            start_x = max(0, min(cx - crop_w // 2, w - crop_w))
            start_y = max(0, min(cy - crop_h // 2, h - crop_h))
            actual_cx = cx
            actual_cy = cy
        else:
            start_x = (w - crop_w) // 2
            start_y = (h - crop_h) // 2
            actual_cx = start_x + crop_w // 2
            actual_cy = start_y + crop_h // 2
    
    data_crop = data[start_y:start_y+crop_h, start_x:start_x+crop_w]
    
    z_data = data_crop.astype(float)
    z_data = np.nan_to_num(z_data, nan=0.0, posinf=0.0, neginf=0.0)
    
    if plot3d:
        z_data_3d = z_data.copy()
    else:
        z_data_3d = np.array([])
    

    
    if z_data.size > 0:
        crop_med = float(np.median(z_data))
        crop_mad = float(np.median(np.abs(z_data - crop_med)))
        z_max = (crop_med + k_val * crop_mad) * 2.0
    else:
        z_max = 255.0
    if z_max <= 0:
        z_max = 255.0

    # Calculate 1D medians for full image banding analysis
    col_medians = np.median(data, axis=0)
    row_medians = np.median(data, axis=1)
    col_medians_list = [float(x) for x in col_medians]
    row_medians_list = [float(x) for x in row_medians]
    col_x_list = list(range(len(col_medians_list)))
    row_x_list = list(range(len(row_medians_list)))

    # Calculate 16x16 medians and MADs
    grid_h, grid_w = h / 16.0, w / 16.0
    medians_16x16 = np.zeros((16, 16))
    mads_16x16 = np.zeros((16, 16))
    for i in range(16):
        for j in range(16):
            r_start = int(i * grid_h)
            r_end = int((i+1)*grid_h) if i < 15 else h
            c_start = int(j * grid_w)
            c_end = int((j+1)*grid_w) if j < 15 else w
            region = data[r_start:r_end, c_start:c_end]
            if region.size > 0:
                med = float(np.median(region))
                medians_16x16[i, j] = med
                mads_16x16[i, j] = float(np.median(np.abs(region - med)))

    overall_med = float(np.median(data))
    overall_mad = float(np.median(np.abs(data - overall_med)))
    global_threshold_severe = overall_med + k_val * overall_mad
    global_threshold_mild = overall_med + (k_val / 10.0) * overall_mad

    all_hotspots = []
    # Hotspot count grid (16x16)
    hotspot_counts_16x16 = np.zeros((16, 16), dtype=int)
    total_hotspots = 0
    for i in range(16):
        for j in range(16):
            r_start = int(i * grid_h)
            r_end = int((i+1)*grid_h) if i < 15 else h
            c_start = int(j * grid_w)
            c_end = int((j+1)*grid_w) if j < 15 else w
            region = data[r_start:r_end, c_start:c_end]
            if region.size > 0:
                if use_global_mad:
                    ref_med = overall_med
                    ref_mad = overall_mad
                else:
                    ref_med = medians_16x16[i, j]
                    ref_mad = mads_16x16[i, j]
                
                threshold_severe = ref_med + k_val * ref_mad
                threshold_mild = ref_med + (k_val / 10.0) * ref_mad
                mask = region > threshold_mild

                if has_scipy:
                    labeled_array, num_features = label(mask)
                    if num_features > 0:
                        import scipy.ndimage as ndi
                        peaks = ndi.maximum_position(region, labels=labeled_array, index=np.arange(1, num_features + 1))
                        for y_local, x_local in peaks:
                            val = float(region[int(y_local), int(x_local)])
                            is_severe = bool(val > threshold_severe)
                            all_hotspots.append({"x": int(x_local + c_start), "y": int(y_local + r_start), "val": val, "grid_r": i, "grid_c": j, "is_severe": is_severe})
                            if is_severe:
                                total_hotspots += 1
                                hotspot_counts_16x16[i, j] += 1
                else:
                    ys, xs = np.where(mask)
                    if len(ys) > 0:
                        vals = region[ys, xs]
                        if len(ys) > 100:
                            idx = np.argpartition(vals, -100)[-100:]
                            ys = ys[idx]
                            xs = xs[idx]
                            vals = vals[idx]
                        for y_local, x_local, val in zip(ys, xs, vals):
                            val = float(val)
                            is_severe = bool(val > threshold_severe)
                            all_hotspots.append({"x": int(x_local + c_start), "y": int(y_local + r_start), "val": val, "grid_r": i, "grid_c": j, "is_severe": is_severe})
                            if is_severe:
                                total_hotspots += 1
                                hotspot_counts_16x16[i, j] += 1

                hotspot_counts_16x16[i, j] = min(hotspot_counts_16x16[i, j], 200)

    # Sort hotspots by value descending
    all_hotspots.sort(key=lambda item: item["val"], reverse=True)
    hotspots = [hs for hs in all_hotspots if hs["is_severe"]][:50]
    
    if len(all_hotspots) > 5000:
        all_hotspots = all_hotspots[:5000]

    if len(all_hotspots) > 5000:
        all_hotspots = all_hotspots[:5000]

    
    all_hotspot_vals_severe = [float(hs["val"]) for hs in all_hotspots if hs["is_severe"]]
    all_hotspot_vals_mild = [float(hs["val"]) for hs in all_hotspots if not hs["is_severe"]]
    
    medians_1d = [float(x) for x in medians_16x16.flatten()]

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Dark Image 3D View</title>
        <link rel="stylesheet" href="/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        <style>
            .dark-layout-4col {
                display: grid;
                grid-template-columns: 13% 30% 30% 27%;
                gap: 1rem;
                height: calc(100vh - 120px);
            }
            .col-files { background: var(--bg-sidebar); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-center { position: relative; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
            .col-right { display: flex; flex-direction: column; gap: 1rem; height: calc(100vh - 120px); }
            .side-plot { flex: 1; background: var(--bg-card); border: 1px solid var(--glass-border); border-radius: 12px; overflow: hidden; position: relative; }
            #plot { flex: 1; min-height: 55%; position: relative; }
            .line-plots-container { display: flex; flex-direction: column; height: 45%; border-top: 1px solid var(--glass-border); }
            .line-plot-box { flex: 1; padding: 5px 10px; position: relative; display: flex; flex-direction: column; }
            /* Adjust list-item height and font based on previous request while keeping LOGDATA design */
            .list-item { padding: 8px 8px !important; }
            .file-name { font-size: 0.68rem !important; }
            .highlighted-grid-item {
                border: 2px solid red !important;
                box-sizing: border-box !important;
                z-index: 10;
                position: relative;
            }
        </style>
        <script>
            function changeFile(filename) {
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('file', filename);
                window.location.search = urlParams.toString();
            }
            async function updateCropData(r, c, cx, cy) {
                // Instantly update highlights
                highlightGrid(r, c);

                // Update URL quietly so sharing works
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('grid_row', r);
                urlParams.set('grid_col', c);
                urlParams.set('cx', cx);
                urlParams.set('cy', cy);
                window.history.replaceState({}, '', '?' + urlParams.toString());
                
                // Sync the inputs
                document.getElementById('crop-x').value = cx;
                document.getElementById('crop-y').value = cy;

                // Stop if plot3d is OFF
                if (!document.getElementById('plot3d-toggle').checked) {
                    return;
                }

                // Fetch new 3D data and render
                document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:var(--text-dim); font-size:0.8rem;">Loading 3D Data...</div>';
                var fetchUrl = `/api/starforge/dark_crop_3d?dir=${encodeURIComponent('__DIR__')}&session=${encodeURIComponent('__SESSION__')}&file=${encodeURIComponent('__FILE__')}&out_dir=${encodeURIComponent('__OUT_DIR__')}&grid_row=${r}&grid_col=${c}&cx=${cx}&cy=${cy}&k_val=${document.getElementById('k-val').value}`;
                
                try {
                    const response = await fetch(fetchUrl);
                    const result = await response.json();
                    
                    if (result.error) throw new Error(result.error);
                    
                    var new_z = result.z_data;
                    if (new_z && new_z.length > 0 && new_z[0].length > 0) {
                        var aspect_x = new_z[0].length / Math.max(new_z.length, new_z[0].length);
                        var aspect_y = new_z.length / Math.max(new_z.length, new_z[0].length);
                        var data3d = [{
                            z: new_z,
                            type: 'surface',
                            colorscale: 'Viridis',
                            cmin: 0,
                            cmax: result.z_max,
                            showscale: false
                        }];
                        var zmin = parseFloat(document.getElementById('z-min').value);
                        var zmax = parseFloat(document.getElementById('z-max').value);
                        if (isNaN(zmin)) zmin = 0;
                        if (isNaN(zmax)) zmax = result.z_max;

                        var layout3d = {
                            autosize: true,
                            scene: {
                                xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                                yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                                zaxis: { title: 'Luminance', range: [zmin, zmax], autorange: false },
                                aspectmode: 'manual',
                                aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                                camera: { eye: {x: -1.5, y: -1.5, z: 1.2} }
                            },
                            margin: { l: 0, r: 0, b: 0, t: 0 },
                            paper_bgcolor: '#121212',
                            plot_bgcolor: '#121212'
                        };
                        document.getElementById('plot').innerHTML = ''; // clear loading text
                        Plotly.newPlot('plot', data3d, layout3d, {responsive: true});
                    }
                } catch (e) {
                    document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:#ff3366; font-size:0.8rem;">Error loading 3D Data</div>';
                }
            }

            function updateK() {
                var new_k = document.getElementById('k-val').value;
                var use_global = document.getElementById('global-mad-toggle').checked ? '1' : '0';
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('k_val', new_k);
                urlParams.set('use_global_mad', use_global);
                window.location.search = urlParams.toString();
            }
            function updateCrop() {
                var cx = parseInt(document.getElementById('crop-x').value) || 0;
                var cy = parseInt(document.getElementById('crop-y').value) || 0;
                updateCropData(-1, -1, cx, cy);
            }
            function toggle3DPlot() {
                var isChecked = document.getElementById('plot3d-toggle').checked;
                var urlParams = new URLSearchParams(window.location.search);
                urlParams.set('plot3d', isChecked ? '1' : '0');
                window.history.replaceState({}, '', '?' + urlParams.toString());
                
                if (isChecked) {
                    var cx = parseInt(document.getElementById('crop-x').value) || -1;
                    var cy = parseInt(document.getElementById('crop-y').value) || -1;
                    var r = parseInt(urlParams.get('grid_row'));
                    var c = parseInt(urlParams.get('grid_col'));
                    if (isNaN(r)) r = -1;
                    if (isNaN(c)) c = -1;
                    if (r === -1 && cx === -1 && cy === -1) {
                        r = 0; c = 0; // default
                    }
                    updateCropData(r, c, cx, cy);
                } else {
                    document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:var(--text-dim); font-size:0.8rem;">3D PLOT IS OFF (Enable in Analysis Setting)</div>';
                }
            }
            function highlightGrid(r, c) {
                // Clear existing highlights
                document.querySelectorAll('.highlighted-grid-item').forEach(el => {
                    el.classList.remove('highlighted-grid-item');
                });
                
                // Add highlight to all matching elements
                document.querySelectorAll(`[data-grid-r="${r}"][data-grid-c="${c}"]`).forEach(el => {
                    el.classList.add('highlighted-grid-item');
                });
            }
        </script>
    </head>
    <body>
        <div class="container" style="max-width: 100%; padding: 0 50px; box-sizing: border-box;">
            <header>
                <div class="header-main">
                    <h1>OrionFieldStack <span class="v-tag">Dark Viewer</span></h1>
                </div>
            </header>
            
            <main>
                <div class="dark-layout-4col">
                    <aside class="col-files">
                        <div style="padding: 15px; border-bottom: 1px solid var(--glass-border); background: var(--bg-card);">
                            <h3 style="margin: 0 0 8px 0;">ANALYSIS SETTING</h3>
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <span style="font-size: 0.75rem; color: #ccc; font-weight: bold;">HOTSPOT Thres. factor K:</span>
                                <input type="number" id="k-val" value="__K_VAL__" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateK()">
                            </div>
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
                                <span style="font-size: 0.75rem; color: #ccc; font-weight: bold;">USE GLOBAL MAD:</span>
                                <label style="display: flex; align-items: center; cursor: pointer;">
                                    <input type="checkbox" id="global-mad-toggle" __GLOBAL_MAD_CHECKED__ onchange="updateK()" style="margin: 0; width: auto; background: none; border: none; accent-color: var(--accent-gold);">
                                </label>
                            </div>
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
                                <span style="font-size: 0.75rem; color: #ccc; font-weight: bold;">3D PLOT:</span>
                                <label style="display: flex; align-items: center; cursor: pointer;">
                                    <input type="checkbox" id="plot3d-toggle" __PLOT3D_CHECKED__ onchange="toggle3DPlot()" style="margin: 0; width: auto; background: none; border: none; accent-color: var(--accent-gold);">
                                </label>
                            </div>
                        </div>
                        <div class="list-container" style="flex: 1; padding: 0; display: flex; flex-direction: column; overflow-y: auto;">
                            __OPTIONS__
                        </div>

                    </aside>
                    <div class="col-right">
                        <div style="display: flex; flex-direction: row; gap: 10px; flex: 1.2; overflow: hidden;">
                            <div class="side-plot" style="flex: 1.4; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                                <h3 style="margin: 0 0 8px 0;">ANALYSIS REPORT</h3>
                                <div style="flex: 1; display: flex; flex-direction: column; gap: 8px; overflow-y: auto;">
                                    <div style="background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                            <span style="font-size: 0.65rem; color: var(--text-dim);">Total Hotspots</span>
                                            <span style="font-size: 0.7rem; color: #fff; font-family: 'JetBrains Mono', monospace;">__TOTAL_HOTSPOTS__</span>
                                        </div>
                                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                            <span style="font-size: 0.65rem; color: var(--text-dim);">Global Median</span>
                                            <span style="font-size: 0.7rem; color: #fff; font-family: 'JetBrains Mono', monospace;">__OVERALL_MEDIAN__</span>
                                        </div>
                                        <div style="display: flex; justify-content: space-between;">
                                            <span style="font-size: 0.65rem; color: var(--text-dim);">Global MAD</span>
                                            <span style="font-size: 0.7rem; color: #fff; font-family: 'JetBrains Mono', monospace;">__OVERALL_MAD__</span>
                                        </div>
                                    </div>
                                    <div style="flex: 1; min-height: 90px; display: flex; flex-direction: column;">
                                        <div style="font-size: 0.65rem; color: var(--accent-gold); margin-bottom: 2px;">Hotspot Histogram</div>
                                        <div style="font-size: 0.55rem; color: var(--text-dim); margin-bottom: 2px;">Threshold: Median + K/10&times;MAD</div>
                                        <div id="plot-hs-hist" style="flex: 1; width: 100%; min-height: 70px;"></div>
                                    </div>
                                    <div style="flex: 1; min-height: 90px; display: flex; flex-direction: column;">
                                        <div style="font-size: 0.65rem; color: var(--accent-gold); margin-bottom: 2px;">Block Median Histogram</div>
                                        <div id="plot-med-hist" style="flex: 1; width: 100%; min-height: 70px;"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="side-plot" style="flex: 0.6; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                                <h3 style="margin: 0 0 8px 0;">HOTSPOTS (TOP 50)</h3>
                                <div id="hotspots-list" style="overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 0px;"></div>
                            </div>
                        </div>
                        <div class="side-plot" style="flex: 1; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                            <h3 style="margin: 0 0 2px 0;">16x16 HOTSPOT HEATMAP</h3>
                            <div style="font-size: 0.65rem; color: var(--text-dim); margin-bottom: 6px;">Threshold: Median + K&times;MAD &nbsp;|&nbsp; Total: <span style="color:#fff;">__TOTAL_HOTSPOTS__</span></div>
                            <div id="hotspot-count-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                        </div>
                    </div>
                    <div class="col-right">
                        <div class="side-plot" style="flex: 1; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                            <h3 style="margin: 0 0 8px 0;">16x16 MEDIAN HEATMAP</h3>
                            <div id="median-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                        </div>
                        <div class="side-plot" style="flex: 1; display: flex; flex-direction: column; background: var(--bg-card); padding: 10px; border-radius: 12px; border: 1px solid var(--glass-border);">
                            <h3 style="margin: 0 0 8px 0;">16x16 MAD HEATMAP (Median Absolute Deviation)</h3>
                            <div id="mad-grid" style="display: grid; grid-template-columns: repeat(16, 1fr); gap: 1px; flex: 1;"></div>
                        </div>
                    </div>
                    <div class="col-center">
                        <h3 style="margin: 10px 10px 0 10px;">Local Pixel Surface(3D PLOT)</h3>
                        <div style="position: absolute; top: 35px; left: 10px; z-index: 10; display: flex; flex-direction: column; gap: 8px;">
                            <div style="display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.6); padding: 8px 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                                <span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: bold; margin-right: 4px;">CROP CENTER</span>
                                <label style="font-size: 0.75rem; color: var(--text-dim);">X:</label>
                                <input type="number" id="crop-x" value="__CROP_X__" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;">
                                <label style="font-size: 0.75rem; color: var(--text-dim); margin-left: 4px;">Y:</label>
                                <input type="number" id="crop-y" value="__CROP_Y__" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;">
                                <button onclick="updateCrop()" style="padding: 4px 8px; font-size: 0.7rem; border-radius: 4px; background: #333; color: #fff; border: 1px solid #555; cursor: pointer;">Apply</button>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.6); padding: 8px 12px; border-radius: 8px; border: 1px solid var(--glass-border);">
                                <span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: bold; margin-right: 4px;">Z-AXIS</span>
                                <label style="font-size: 0.75rem; color: var(--text-dim);">Min:</label>
                                <input type="number" id="z-min" value="0" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                                <label style="font-size: 0.75rem; color: var(--text-dim); margin-left: 4px;">Max:</label>
                                <input type="number" id="z-max" value="__ZMAX__" step="any" style="width: 70px; padding: 4px; border-radius: 4px; background: #000; color: #fff; border: 1px solid #444;" onchange="updateZRange()">
                            </div>
                        </div>
                        <div id="plot"></div>
                        <div class="line-plots-container">
                            <div class="line-plot-box">
                                <h3 style="margin: 0 0 2px 0;">Row Median Profile</h3>
                                <div style="font-size: 0.65rem; color: var(--text-dim); margin-bottom: 2px;">Shows Vertical sensor non-uniformity.</div>
                                <div id="plot-row-median" style="flex: 1; width: 100%;"></div>
                            </div>
                            <div class="line-plot-box" style="border-top: 1px solid var(--glass-border);">
                                <h3 style="margin: 4px 0 2px 0;">Column Median Profile</h3>
                                <div style="font-size: 0.65rem; color: var(--text-dim); margin-bottom: 2px;">Shows horizontal sensor non-uniformity.</div>
                                <div id="plot-col-median" style="flex: 1; width: 100%;"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
        <script>
            var z_data = __ZDATA3D__;

 
            // 3D Plot
            if (z_data.length > 0 && z_data[0].length > 0) {
                var data3d = [{
                    z: z_data,
                    type: 'surface',
                    colorscale: 'Viridis',
                    cmin: 0,
                    cmax: __ZMAX__,
                    showscale: false
                }];
                var aspect_x = z_data[0].length / Math.max(z_data.length, z_data[0].length);
                var aspect_y = z_data.length / Math.max(z_data.length, z_data[0].length);

                var layout3d = {
                    autosize: true,
                    scene: {
                        xaxis: { title: 'X', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                        yaxis: { title: 'Y', showgrid: true, zeroline: true, showline: true, showticklabels: true },
                        zaxis: { title: 'Luminance', range: [0, __ZMAX__], autorange: false },
                        aspectmode: 'manual',
                        aspectratio: { x: aspect_x, y: aspect_y, z: 0.25 },
                        camera: {
                            eye: {x: -1.5, y: -1.5, z: 1.2}
                        }
                    },
                    margin: { l: 0, r: 0, b: 0, t: 0 },
                    paper_bgcolor: '#121212',
                    plot_bgcolor: '#121212'
                };
                Plotly.newPlot('plot', data3d, layout3d, {responsive: true});
            } else {
                document.getElementById('plot').innerHTML = '<div style="display:flex; height:100%; align-items:center; justify-content:center; color:var(--text-dim); font-size:0.8rem;">3D PLOT IS OFF (Enable in Analysis Setting)</div>';
            }

            // Shared cell dimensions for click navigation
            var cell_w = __FULL_WIDTH__ / 16.0;
            var cell_h = __FULL_HEIGHT__ / 16.0;
            var sel_row = __GRID_ROW__;
            var sel_col = __GRID_COL__;

            function getClickAttr(i, j) {
                var click_cx = Math.round((j + 0.5) * cell_w);
                var click_cy = Math.round((i + 0.5) * cell_h);
                // Highlight handles the border dynamically now, but we keep onclick
                return `data-grid-r="${i}" data-grid-c="${j}" style="cursor: pointer;" onmouseover="this.style.opacity=0.7;" onmouseout="this.style.opacity=1;" onclick="updateCropData(${i}, ${j}, ${click_cx}, ${click_cy})"`;
            }

            // Populate 16x16 Grid
            var medians = __MEDIANS_16X16__;
            var max_med = -Infinity;
            var min_med = Infinity;
            for(var i=0; i<16; i++) {
                for(var j=0; j<16; j++) {
                    if (medians[i][j] > max_med) max_med = medians[i][j];
                    if (medians[i][j] < min_med) min_med = medians[i][j];
                }
            }
            var gridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = medians[i][j];
                    var norm = max_med > min_med ? (val - min_med) / (max_med - min_med) : 0;
                    var r = Math.round(30 + norm * 225);
                    var g = Math.round(30 + norm * 21);
                    var b = Math.round(30 + norm * 72);
                    gridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" ${getClickAttr(i, j)} title="Row ${i+1}, Col ${j+1}: ${val}">${Number(val.toPrecision(3))}</div>`;
                }
            }
            document.getElementById('median-grid').innerHTML = gridHtml;

            // Populate 16x16 MAD Grid
            var mads = __MADS_16X16__;
            var max_mad = -Infinity;
            var min_mad = Infinity;
            for(var i=0; i<16; i++) {
                for(var j=0; j<16; j++) {
                    if (mads[i][j] > max_mad) max_mad = mads[i][j];
                    if (mads[i][j] < min_mad) min_mad = mads[i][j];
                }
            }
            var madGridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = mads[i][j];
                    var norm = max_mad > min_mad ? (val - min_mad) / (max_mad - min_mad) : 0;
                    var r = Math.round(30 + norm * 123);
                    var g = Math.round(30 + norm * 21);
                    var b = Math.round(30 + norm * 225);
                    madGridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" ${getClickAttr(i, j)} title="Row ${i+1}, Col ${j+1}: ${val}">${Number(val.toPrecision(3))}</div>`;
                }
            }
            document.getElementById('mad-grid').innerHTML = madGridHtml;

            // Populate 16x16 Hotspot Count Grid
            var hs_counts = __HOTSPOT_COUNTS_16X16__;
            var hsGridHtml = '';
            for (var i = 0; i < 16; i++) {
                for (var j = 0; j < 16; j++) {
                    var val = hs_counts[i][j];
                    var r, g, b;
                    if (val === 0) {
                        r = 25; g = 25; b = 25;
                    } else {
                        var norm = Math.min(val / 200.0, 1.0);
                        r = Math.round(120 + norm * 135);
                        g = Math.round(40 + norm * 160);
                        b = Math.round(40 - norm * 40);
                    }
                    var displayVal = val >= 200 ? '200+' : val;
                    hsGridHtml += `<div style="background: rgb(${r},${g},${b}); display: flex; align-items: center; justify-content: center; font-size: 0.45rem; color: #fff; font-family: 'JetBrains Mono', monospace; padding: 2px 0;" ${getClickAttr(i, j)} title="Row ${i+1}, Col ${j+1}: ${displayVal} hotspots">${displayVal}</div>`;
                }
            }
            document.getElementById('hotspot-count-grid').innerHTML = hsGridHtml;

            // Populate Hotspots
            var hotspots = __HOTSPOTS__;
            var hsHtml = '';
            hotspots.forEach((hs, idx) => {
                var hs_grid_col = hs.grid_c;
                var hs_grid_row = hs.grid_r;
                var click_cx = Math.round((hs_grid_col + 0.5) * cell_w);
                var click_cy = Math.round((hs_grid_row + 0.5) * cell_h);
                hsHtml += `<div data-grid-r="${hs_grid_row}" data-grid-c="${hs_grid_col}" style="padding: 2px 4px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.05);" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'" onclick="updateCropData(${hs_grid_row}, ${hs_grid_col}, ${click_cx}, ${click_cy})">
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; color: var(--text-bright);">#${idx+1} <span style="color:var(--accent-gold);">[${hs.x}, ${hs.y}]</span></span>
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; font-weight: bold; color: #ff3366;">${(hs.val/1000).toPrecision(3)}k</span>
                </div>`;
            });
            document.getElementById('hotspots-list').innerHTML = hsHtml;

            function updateZRange() {
                var zmin = parseFloat(document.getElementById('z-min').value);
                var zmax = parseFloat(document.getElementById('z-max').value);
                if (isNaN(zmin)) zmin = 0;
                if (isNaN(zmax)) zmax = __ZMAX__;
                
                Plotly.relayout('plot', {
                    'scene.zaxis.range': [zmin, zmax],
                    'scene.zaxis.autorange': false
                });
                Plotly.restyle('plot', {
                    cmin: [zmin],
                    cmax: [zmax]
                });

            }
            // Force apply range once to ensure 3D scene correctly clips
            if (document.getElementById('z-min') && z_data.length > 0) {
                updateZRange();
            }

            // Apply grid highlight on load for the selected grid
            if (sel_row >= 0 && sel_col >= 0) {
                highlightGrid(sel_row, sel_col);
            }

            // Render 1D Line plots
            var rowMedians = __ROW_MEDIANS__;
            var rowX = __ROW_X__;
            var colMedians = __COL_MEDIANS__;
            var colX = __COL_X__;

            var commonLayout = {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                margin: { l: 40, r: 10, t: 10, b: 20 },
                font: { color: '#ccc', size: 10 },
                xaxis: { showgrid: true, gridcolor: 'rgba(255,255,255,0.1)' },
                yaxis: { showgrid: true, gridcolor: 'rgba(255,255,255,0.1)' }
            };

            Plotly.newPlot('plot-row-median', [{
                x: rowX,
                y: rowMedians,
                type: 'scatter',
                mode: 'lines',
                line: { color: '#ff3366', width: 1 }
            }], commonLayout, { responsive: true, scrollZoom: true });

            Plotly.newPlot('plot-col-median', [{
                x: colX,
                y: colMedians,
                type: 'scatter',
                mode: 'lines',
                line: { color: '#33ccff', width: 1 }
            }], commonLayout, { responsive: true, scrollZoom: true });

            // Render Histograms in Analysis Report
            var hsValsSevere = __ALL_HOTSPOT_VALS_SEVERE__;
            var hsValsMild = __ALL_HOTSPOT_VALS_MILD__;
            var medians1D = __MEDIANS_1D__;

            var histLayout = {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                margin: { l: 25, r: 10, t: 10, b: 20 },
                font: { color: '#ccc', size: 9 },
                xaxis: { showgrid: false, zeroline: false },
                yaxis: { showgrid: true, gridcolor: 'rgba(255,255,255,0.1)', zeroline: false },
                showlegend: false,
                bargap: 0.05
            };
            var histLayoutStacked = JSON.parse(JSON.stringify(histLayout));
            histLayoutStacked.barmode = 'stack';
            histLayoutStacked.yaxis.type = 'log';

            var maxHs = Math.max(...hsValsSevere, ...hsValsMild, 1e-9);
            var hsXbins = { start: 0, end: maxHs, size: maxHs / 20 };
            
            var useGlobalMad = parseInt('__USE_GLOBAL_MAD__');
            if (useGlobalMad === 1) {
                var thrSevere = parseFloat('__GLOBAL_THRESHOLD_SEVERE__');
                var thrMild = parseFloat('__GLOBAL_THRESHOLD_MILD__');
                
                histLayoutStacked.shapes = [
                    { type: 'line', x0: thrMild, x1: thrMild, y0: 0, y1: 1, yref: 'paper', line: { color: '#ffcc00', width: 1, dash: 'dash' } },
                    { type: 'line', x0: thrSevere, x1: thrSevere, y0: 0, y1: 1, yref: 'paper', line: { color: '#ff3366', width: 1, dash: 'dash' } }
                ];
                var textMild = 'TH: ' + (thrMild / 1000).toPrecision(3) + 'k';
                var textSevere = 'TH: ' + (thrSevere / 1000).toPrecision(3) + 'k';
                histLayoutStacked.annotations = [
                    { x: thrMild, y: 1.0, yref: 'paper', text: textMild, showarrow: false, font: { color: '#ffcc00', size: 9 }, xanchor: 'left', yanchor: 'bottom' },
                    { x: thrSevere, y: 1.0, yref: 'paper', text: textSevere, showarrow: false, font: { color: '#ff3366', size: 9 }, xanchor: 'left', yanchor: 'bottom' }
                ];
                histLayoutStacked.margin.t = 15;
            }

            Plotly.newPlot('plot-hs-hist', [
                {
                    x: hsValsMild,
                    type: 'histogram',
                    marker: { color: '#ffcc00', opacity: 0.8 },
                    name: 'Mild',
                    xbins: hsXbins
                },
                {
                    x: hsValsSevere,
                    type: 'histogram',
                    marker: { color: '#ff3366', opacity: 0.8 },
                    name: 'Severe',
                    xbins: hsXbins
                }
            ], histLayoutStacked, { responsive: true, displayModeBar: false });

            var maxMed = Math.max(...medians1D, 1e-9);
            var medXbins = { start: 0, end: maxMed, size: maxMed / 20 };

            Plotly.newPlot('plot-med-hist', [{
                x: medians1D,
                type: 'histogram',
                marker: { color: '#33ccff', opacity: 0.8 },
                xbins: medXbins
            }], histLayout, { responsive: true, displayModeBar: false });
        </script>
    </body>
    </html>
    '''
    html = html_template.replace('__FILENAME__', file_path)\
        .replace('__ZDATA3D__', json.dumps(z_data_3d.tolist()))\
        .replace('__MEDIANS_16X16__', json.dumps(medians_16x16.tolist()))\
        .replace('__MADS_16X16__', json.dumps(mads_16x16.tolist()))\
        .replace('__ROW_MEDIANS__', json.dumps(row_medians_list))\
        .replace('__ROW_X__', json.dumps(row_x_list))\
        .replace('__COL_MEDIANS__', json.dumps(col_medians_list))\
        .replace('__COL_X__', json.dumps(col_x_list))\
        .replace('__HOTSPOT_COUNTS_16X16__', json.dumps(hotspot_counts_16x16.tolist()))\
        .replace('__TOTAL_HOTSPOTS__', str(total_hotspots))\
        .replace('__OVERALL_MEDIAN__', f"{overall_med:.2f}")\
        .replace('__OVERALL_MAD__', f"{overall_mad:.2f}")\
        .replace('__USE_GLOBAL_MAD__', str(use_global_mad))\
        .replace('__GLOBAL_THRESHOLD_SEVERE__', f"{global_threshold_severe:.2f}")\
        .replace('__GLOBAL_THRESHOLD_MILD__', f"{global_threshold_mild:.2f}")\
        .replace('__ALL_HOTSPOT_VALS_SEVERE__', json.dumps(all_hotspot_vals_severe))\
        .replace('__ALL_HOTSPOT_VALS_MILD__', json.dumps(all_hotspot_vals_mild))\
        .replace('__MEDIANS_1D__', json.dumps(medians_1d))\
        .replace('__HOTSPOTS__', json.dumps(hotspots))\
        .replace('__ZMAX__', str(z_max))\
        .replace('__ZDATA_FULL_LENGTH__', str(len(z_data)))\
        .replace('__ZDATA_FULL_WIDTH__', str(len(z_data[0]) if len(z_data) > 0 else 0))\
        .replace('__FULL_WIDTH__', str(w))\
        .replace('__FULL_HEIGHT__', str(h))\
        .replace('__CROP_X__', str(actual_cx))\
        .replace('__CROP_Y__', str(actual_cy))\
        .replace('__GRID_ROW__', str(grid_row))\
        .replace('__GRID_COL__', str(grid_col))\
        .replace('__PLOT3D_CHECKED__', "checked" if plot3d == 1 else "")\
        .replace('__GLOBAL_MAD_CHECKED__', "checked" if use_global_mad == 1 else "")
    print(html)
except Exception as e:
    print(f"<html><body><h3>Error processing image: {str(e)}</h3></body></html>")
"""
    try:
        from fastapi.responses import HTMLResponse
        proc = await asyncio.create_subprocess_exec(
            get_starforge_python(), "-c", python_code, target_file, cx, cy, grid_row, grid_col, k_val, plot3d, use_global_mad,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return HTMLResponse(f"<html><body><h3>Error: Script execution failed.</h3><pre>{stderr.decode(errors='replace')}</pre></body></html>", status_code=500)
            
        final_html = stdout.decode(errors='replace') \
            .replace('__OPTIONS__', options_html) \
            .replace('__K_VAL__', k_val) \
            .replace('__DIR__', dir) \
            .replace('__SESSION__', session) \
            .replace('__FILE__', file) \
            .replace('__OUT_DIR__', out_dir)
        return HTMLResponse(final_html)
    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<html><body><h3>Error: {str(e)}</h3></body></html>", status_code=500)


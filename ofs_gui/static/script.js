document.addEventListener('DOMContentLoaded', () => {
    // --- Global Elements ---
    const connectionStatus = document.getElementById('connection-status');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanels = document.querySelectorAll('.tab-panel');

    // --- Tab Switching ---
    tabBtns.forEach(btn => {
        btn.onclick = () => {
            const target = btn.dataset.tab;
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanels.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`${target}-tab`).classList.add('active');
        };
    });

    // =========================================================================
    // UTILS
    // =========================================================================
    function formatTime(isoStr) {
        if (!isoStr || typeof isoStr !== 'string' || !isoStr.includes('T')) return '--:--:--';
        try {
            return isoStr.split('T')[1].split('.')[0];
        } catch (e) { return '--:--:--'; }
    }

    function stripAnsi(text) {
        return text.replace(/\x1B\[[0-9;]*[mK]/g, '');
    }

    // =========================================================================
    // COMMON: FOLDER PICKER
    // =========================================================================
    const pickerModal = document.getElementById('folder-picker-modal');
    const closePickerBtn = document.getElementById('close-picker-btn');
    const pickerList = document.getElementById('picker-list');
    const pickerCurrentPath = document.getElementById('picker-current-path');
    const pickerUpBtn = document.getElementById('picker-up-btn');
    const confirmPickerBtn = document.getElementById('confirm-picker-btn');
    
    let currentPickerPath = '';
    let activeFolderInput = null;

    async function loadFolders(path) {
        try {
            const resp = await fetch(`/api/utils/list_dirs?path=${encodeURIComponent(path)}`);
            const data = await resp.json();
            currentPickerPath = data.current;
            pickerCurrentPath.textContent = data.current;
            
            pickerList.innerHTML = '';
            data.dirs.forEach(dir => {
                const div = document.createElement('div');
                div.className = 'folder-item';
                div.textContent = dir;
                div.onclick = () => loadFolders(`${currentPickerPath}/${dir}`);
                pickerList.appendChild(div);
            });
            
            pickerUpBtn.onclick = () => loadFolders(data.parent);
        } catch (e) { 
            console.error('Failed to load folders', e); 
            pickerList.innerHTML = `<div class="error">Error: ${e.message}</div>`;
        }
    }

    function initFolderPicker(btnId, inputId) {
        const btn = document.getElementById(btnId);
        const input = document.getElementById(inputId);
        if (btn && input) {
            btn.onclick = () => {
                activeFolderInput = input;
                pickerModal.classList.remove('hidden');
                loadFolders(input.value || '~');
            };
        }
    }

    initFolderPicker('browse-dir-btn', 'save_dir');
    initFolderPicker('browse-log-path-btn', 'log-path');

    closePickerBtn.onclick = () => pickerModal.classList.add('hidden');
    confirmPickerBtn.onclick = () => {
        if (activeFolderInput) activeFolderInput.value = currentPickerPath;
        pickerModal.classList.add('hidden');
    };

    // =========================================================================
    // SHUTTER TAB LOGIC
    // =========================================================================
    const shutterForm = document.getElementById('shutter-form');
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const saveDefaultBtn = document.getElementById('save-default-btn');
    const terminal = document.getElementById('terminal');
    const clearBtn = document.getElementById('clear-log');
    const toggleAdvancedBtn = document.getElementById('toggle-advanced');
    const advancedPanel = document.getElementById('advanced-settings');
    const frameTypeSelect = document.getElementById('frame_type_select');
    const frameTypeInput = document.getElementById('frame_type');

    const statLabel = document.getElementById('stat-label');
    const statTarget = document.getElementById('stat-target');
    const statShots = document.getElementById('stat-shots');
    const statMode = document.getElementById('stat-mode');
    const progressBar = document.getElementById('progress-bar');

    let shutterEventSource = null;

    function updateDashboard(line) {
        const cleanLine = stripAnsi(line);
        if (cleanLine.includes('Target:')) {
            const parts = cleanLine.split('Target:');
            if (parts.length > 1) statTarget.textContent = parts[1].trim();
        }
        const shotMatch = cleanLine.match(/Shutter ON \((\d+)\/(\d+|Inf)\)/);
        if (shotMatch) {
            const current = parseInt(shotMatch[1]);
            const totalStr = shotMatch[2];
            const total = totalStr === 'Inf' ? 0 : parseInt(totalStr);
            statLabel.textContent = 'EXPOSING';
            statLabel.className = 'badge exposing';
            statShots.textContent = `${current} / ${totalStr}`;
            if (total > 0) progressBar.style.width = `${(current / total) * 100}%`;
            else progressBar.style.width = '100%';
        }
        if (cleanLine.includes('Downloading:')) {
            statLabel.textContent = 'DOWNLOADING';
            statLabel.className = 'badge waiting';
        }
        if (cleanLine.includes('Waiting for background tasks')) {
            statLabel.textContent = 'FINISHING';
            statLabel.className = 'badge waiting';
        }
        if (cleanLine.includes('### Finished Session')) {
            statLabel.textContent = 'IDLE';
            statLabel.className = 'badge idle';
            progressBar.style.width = '100%';
        }
    }

    frameTypeSelect.onchange = () => {
        if (frameTypeSelect.value === 'custom') {
            frameTypeInput.classList.remove('hidden');
            frameTypeInput.focus();
        } else {
            frameTypeInput.classList.add('hidden');
            frameTypeInput.value = frameTypeSelect.value;
        }
    };

    toggleAdvancedBtn.onclick = () => {
        const isActive = advancedPanel.classList.toggle('active');
        toggleAdvancedBtn.classList.toggle('active');
        toggleAdvancedBtn.querySelector('.icon').textContent = isActive ? '▴' : '▾';
    };

    function addTerminalLog(text, type = '') {
        const cleanText = stripAnsi(text).trim();
        if (!cleanText) return;
        const div = document.createElement('div');
        div.className = `log-line ${type}`;
        if (cleanText.includes('Shutter ON')) div.classList.add('shutter-on');
        if (cleanText.toLowerCase().includes('error')) div.classList.add('error');
        div.textContent = cleanText;
        terminal.appendChild(div);
        terminal.scrollTop = terminal.scrollHeight;
    }

    function setShutterStatus(running) {
        if (running) {
            connectionStatus.textContent = 'SYSTEM RUNNING';
            connectionStatus.className = 'status-running';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else {
            connectionStatus.textContent = 'SYSTEM IDLE';
            connectionStatus.className = 'status-idle';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }
    }

    async function loadGuiConfig() {
        try {
            const resp = await fetch('/api/config/load');
            const config = await resp.json();
            for (const key in config) {
                const input = document.getElementById(key);
                if (input) {
                    input.value = config[key];
                    if (key === 'frame_type') {
                        const standardTypes = ['test', 'light', 'dark', 'flat', 'bias'];
                        if (standardTypes.includes(config[key])) {
                            frameTypeSelect.value = config[key];
                            frameTypeInput.classList.add('hidden');
                        } else {
                            frameTypeSelect.value = 'custom';
                            frameTypeInput.classList.remove('hidden');
                        }
                    }
                }
            }
            addTerminalLog('>>> Default configuration loaded.', 'system');
        } catch (e) { console.error('Failed to load config', e); }
    }

    saveDefaultBtn.onclick = async () => {
        const config = {};
        const inputs = shutterForm.querySelectorAll('input, select');
        inputs.forEach(input => { if (input.id) config[input.id] = input.value; });
        try {
            const resp = await fetch('/api/config/save', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            if (resp.ok) addTerminalLog('>>> Configuration saved as default.', 'system');
            else addTerminalLog('>>> Failed to save configuration.', 'error');
        } catch (e) { addTerminalLog(`Save Error: ${e.message}`, 'error'); }
    };

    function startShutterLogStream() {
        if (shutterEventSource) shutterEventSource.close();
        shutterEventSource = new EventSource('/api/shutter/logs');
        shutterEventSource.onmessage = (event) => {
            if (event.data === '[Process Finished]') {
                setShutterStatus(false); shutterEventSource.close();
                addTerminalLog('--- Session Finished ---', 'system');
                updateDashboard('### Finished Session'); 
            } else {
                addTerminalLog(event.data);
                updateDashboard(event.data);
            }
        };
        shutterEventSource.onerror = () => shutterEventSource.close();
    }

    shutterForm.onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(shutterForm);
        statTarget.textContent = formData.get('objective') || 'N/A';
        statMode.textContent = formData.get('mode').toUpperCase() || 'N/A';
        statShots.textContent = `0 / ${formData.get('shots')}`;
        progressBar.style.width = '0%';
        try {
            addTerminalLog('>>> Starting session...', 'system');
            const resp = await fetch('/api/shutter/start', { method: 'POST', body: formData });
            if (resp.ok) { setShutterStatus(true); startShutterLogStream(); }
            else addTerminalLog(`ERROR: ${(await resp.json()).detail}`, 'error');
        } catch (e) { addTerminalLog(`Connection Error: ${e.message}`, 'error'); }
    };

    stopBtn.onclick = async () => {
        try { addTerminalLog('>>> Aborting session...', 'system'); await fetch('/api/shutter/stop', { method: 'POST' }); }
        catch (e) { addTerminalLog(`Abort failed: ${e.message}`, 'error'); }
    };

    clearBtn.onclick = () => { terminal.innerHTML = ''; addTerminalLog('Console cleared.', 'system'); };

    // =========================================================================
    // LOGDATA TAB LOGIC (INTERACTIVE 3-COLUMN)
    // =========================================================================
    const loadLogsBtn = document.getElementById('load-logs-btn');
    const sessionList = document.getElementById('session-list');
    const fileList = document.getElementById('file-list');
    const logContent = document.getElementById('log-content');
    const detailPlaceholder = document.getElementById('log-detail-placeholder');
    const imgContainer = document.getElementById('image-preview-container');
    const imgInfo = document.getElementById('image-info');
    const metaTable = document.getElementById('metadata-table');
    const metaJson = document.getElementById('metadata-json');
    const metaTabBtns = document.querySelectorAll('.meta-tab-btn');
    const metaPanels = document.querySelectorAll('.meta-panel');

    // Image Modal Elements
    const imageModal = document.getElementById('image-modal');
    const enlargedImage = document.getElementById('enlarged-image');
    const closeImageModal = document.getElementById('close-image-modal');
    const imageModalOverlay = document.getElementById('image-modal-overlay');

    let currentSessionsMap = new Map();

    // --- Image Zoom & Pan State ---
    let zoomScale = 1;
    let zoomPosX = 0;
    let zoomPosY = 0;
    let isPanning = false;
    let startX = 0;
    let startY = 0;

    function updateZoomTransform() {
        enlargedImage.style.transform = `translate(${zoomPosX}px, ${zoomPosY}px) scale(${zoomScale})`;
    }

    function resetZoomState() {
        zoomScale = 1; zoomPosX = 0; zoomPosY = 0;
        updateZoomTransform();
    }

    imgContainer.onclick = () => {
        const img = imgContainer.querySelector('img');
        if (img && img.src) {
            enlargedImage.src = img.src;
            imageModal.classList.remove('hidden');
            resetZoomState();
        }
    };

    closeImageModal.onclick = () => imageModal.classList.add('hidden');
    imageModalOverlay.onclick = () => imageModal.classList.add('hidden');

    // Zoom Logic
    enlargedImage.onwheel = (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.85 : 1.15;
        const newScale = Math.min(Math.max(0.1, zoomScale * delta), 20);
        zoomScale = newScale;
        updateZoomTransform();
    };

    // Pan Logic
    enlargedImage.onmousedown = (e) => {
        e.preventDefault();
        isPanning = true;
        startX = e.clientX - zoomPosX;
        startY = e.clientY - zoomPosY;
        enlargedImage.style.cursor = 'grabbing';
    };

    window.addEventListener('mousemove', (e) => {
        if (!isPanning) return;
        zoomPosX = e.clientX - startX;
        zoomPosY = e.clientY - startY;
        updateZoomTransform();
    });

    window.addEventListener('mouseup', () => {
        if (isPanning) {
            isPanning = false;
            enlargedImage.style.cursor = 'grab';
        }
    });

    metaTabBtns.forEach(btn => {
        btn.onclick = () => {
            const target = btn.dataset.meta;
            metaTabBtns.forEach(b => b.classList.remove('active'));
            metaPanels.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`meta-${target}-view`).classList.add('active');
        };
    });

    loadLogsBtn.onclick = async () => {
        const path = document.getElementById('log-path').value.trim();
        if (!path) return;
        sessionList.innerHTML = '<div class="placeholder">Loading...</div>';
        fileList.innerHTML = '<div class="placeholder">Waiting...</div>';
        logContent.classList.add('hidden');
        detailPlaceholder.classList.remove('hidden');

        // Reset SSE targets
        selectedSessionId = null;
        selectedFileName = null;
        sseTargetSessionOpt.disabled = true;
        sseTargetFileOpt.disabled = true;
        sseTargetSelect.value = 'folder';

        try {
            const resp = await fetch(`/api/logs/browse?path=${encodeURIComponent(path)}`);
            if (!resp.ok) throw new Error((await resp.json()).detail || 'Failed to load logs');
            const data = await resp.json();
            currentSessionsMap = new Map();
            data.forEach(record => {
                const sid = record.session_id || 'Unknown';
                if (!currentSessionsMap.has(sid)) currentSessionsMap.set(sid, []);
                currentSessionsMap.get(sid).push(record);
            });
            renderSessions();
        } catch (e) { sessionList.innerHTML = `<div class="placeholder error">Error: ${e.message}</div>`; }
    };

    function renderSessions() {
        sessionList.innerHTML = '';
        if (currentSessionsMap.size === 0) {
            sessionList.innerHTML = '<div class="placeholder">No sessions found</div>';
            return;
        }
        const sortedIds = Array.from(currentSessionsMap.keys()).sort().reverse();
        sortedIds.forEach(sid => {
            const records = currentSessionsMap.get(sid);
            const obj = records[0]?.objective || 'N/A';
            const item = document.createElement('div');
            item.className = 'list-item';
            item.innerHTML = `<span class="session-name">${sid}</span><span class="session-obj">${obj}</span>`;
            item.onclick = () => {
                document.querySelectorAll('.col-sessions .list-item').forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');
                selectedSessionId = sid;
                sseTargetSessionOpt.disabled = false;
                if (sseTargetSelect.value === 'folder') {
                    sseTargetSelect.value = 'session';
                }
                renderFiles(sid);
            };
            sessionList.appendChild(item);
        });
    }

    function renderFiles(sessionId) {
        fileList.innerHTML = '';
        const records = currentSessionsMap.get(sessionId) || [];
        records.forEach(record => {
            const time = formatTime(record.record?.meta?.iso_timestamp);
            const fileName = record.record?.file?.name || 'Unknown';
            const item = document.createElement('div');
            item.className = 'list-item';
            item.innerHTML = `<span class="file-name">${fileName}</span><span class="file-time">${time}</span>`;
            item.onclick = () => {
                document.querySelectorAll('.col-files .list-item').forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');
                selectedFileName = fileName;
                sseTargetFileOpt.disabled = false;
                if (sseTargetSelect.value === 'folder' || sseTargetSelect.value === 'session') {
                    // Do not auto-switch to file target on simple click, but keep option enabled
                }
                showDetail(record);
            };
            fileList.appendChild(item);
        });
        const firstFile = fileList.querySelector('.list-item');
        if (firstFile) firstFile.click();
    }

    function showDetail(record) {
        detailPlaceholder.classList.add('hidden');
        logContent.classList.remove('hidden');
        imgContainer.innerHTML = '<div class="placeholder">Loading preview...</div>';
        const fileName = record.record?.file?.name || '';
        const filePath = record.record?.file?.path || '';
        if (fileName) {
            const img = document.createElement('img');
            img.src = `/api/logs/image?path=${encodeURIComponent(filePath + '/' + fileName)}`;
            img.onerror = () => imgContainer.innerHTML = `<div class="no-preview">Preview not available</div>`;
            img.onload = () => { imgContainer.innerHTML = ''; imgContainer.appendChild(img); };
        }
        imgInfo.textContent = `File: ${fileName} | ${record.record?.file?.format} | ${record.record?.file?.size_mb} MB`;
        
        metaTable.innerHTML = '';
        const rows = [
            ['Objective', record?.objective],
            ['Session / Time', `${record?.session_id} / ${formatTime(record?.record?.meta?.iso_timestamp)}`],
            ['Exposure / ISO', `${record?.record?.meta?.exposure_actual_sec || 'N/A'}s / ISO ${record?.record?.exif?.iso || 'N/A'}`],
            ['RA / DEC', `${record?.record?.mount?.ra_hms || 'N/A'} / ${record?.record?.mount?.dec_dms || 'N/A'}`],
            ['Pier / Site', `${record?.record?.mount?.side_of_pier || 'N/A'} / ${record?.record?.location?.site_name || 'N/A'}`],
            ['SF Median', `FWHM: ${record?.analysis?.SF?.quality?.sf_fwhm_med?.toFixed(2) || 'N/A'} / Ell: ${record?.analysis?.SF?.quality?.sf_ell_med?.toFixed(2) || 'N/A'}`],
            ['Equipment', `${record?.equipment?.telescope || 'N/A'} / ${record?.equipment?.camera || 'N/A'}`]
        ];
        rows.forEach(([key, val]) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<th>${key}</th><td>${val || 'N/A'}</td>`;
            metaTable.appendChild(tr);
        });
        metaJson.textContent = JSON.stringify(record, null, 2);
    }

    // =========================================================================
    // SSE RUNNER LOGIC
    // =========================================================================
    const sseTargetSelect = document.getElementById('sse-target');
    const sseTargetSessionOpt = document.getElementById('sse-target-session-opt');
    const sseTargetFileOpt = document.getElementById('sse-target-file-opt');
    const sseAllskyCheckbox = document.getElementById('sse-allsky');
    const sseForceCheckbox = document.getElementById('sse-force');
    const sseRunBtn = document.getElementById('sse-run-btn');
    const sseStopBtn = document.getElementById('sse-stop-btn');
    const sseConsoleModal = document.getElementById('sse-console-modal');
    const closeSseModalBtn = document.getElementById('close-sse-modal-btn');
    const sseModalCloseBtn = document.getElementById('sse-modal-close-btn');
    const sseTerminal = document.getElementById('sse-terminal');
    const sseModalStatus = document.getElementById('sse-modal-status');
    const logPathInput = document.getElementById('log-path');
    
    // Status bar elements
    const sseStatusBar = document.getElementById('sse-status-bar');
    const sseStatusText = document.getElementById('sse-status-text');
    const sseStatusFile = document.getElementById('sse-status-file');

    let selectedSessionId = null;
    let selectedFileName = null;
    let sseEventSource = null;

    function addSseTerminalLog(text, type = '') {
        const cleanText = stripAnsi(text).trim();
        if (!cleanText) return;
        const div = document.createElement('div');
        div.className = `log-line ${type}`;
        if (cleanText.toLowerCase().includes('success') || cleanText.toLowerCase().includes('solved')) div.classList.add('shutter-on');
        if (cleanText.toLowerCase().includes('error') || cleanText.toLowerCase().includes('fail')) div.classList.add('error');
        div.textContent = cleanText;
        sseTerminal.appendChild(div);
        sseTerminal.scrollTop = sseTerminal.scrollHeight;
    }

    function setSseStatus(running, endStatus = '') {
        if (running) {
            sseRunBtn.disabled = true;
            sseStopBtn.disabled = false;
            sseModalStatus.textContent = 'Running...';
            sseModalStatus.style.color = 'var(--accent-blue)';
            
            // Show main window status bar
            sseStatusBar.classList.remove('hidden');
            sseStatusText.textContent = 'SSE Running...';
            sseStatusText.style.color = 'var(--accent-blue)';
            sseStatusFile.textContent = 'Starting...';
            const spinner = sseStatusBar.querySelector('.sse-spinner');
            if (spinner) spinner.style.display = 'inline-block';
        } else {
            sseRunBtn.disabled = false;
            sseStopBtn.disabled = true;
            
            const label = endStatus || 'Idle';
            sseModalStatus.textContent = label;
            
            if (label.toLowerCase().includes('finished') || label.toLowerCase().includes('success')) {
                sseModalStatus.style.color = '#00ff88';
                sseStatusText.textContent = 'SSE Finished';
                sseStatusText.style.color = '#00ff88';
            } else if (label.toLowerCase().includes('stopped') || label.toLowerCase().includes('error') || label.toLowerCase().includes('failed')) {
                sseModalStatus.style.color = 'var(--accent-red)';
                sseStatusText.textContent = label;
                sseStatusText.style.color = 'var(--accent-red)';
            } else {
                sseModalStatus.style.color = 'var(--text-dim)';
                sseStatusText.textContent = 'SSE Idle';
                sseStatusText.style.color = 'var(--text-dim)';
            }
            
            const spinner = sseStatusBar.querySelector('.sse-spinner');
            if (spinner) spinner.style.display = 'none';
            sseStatusFile.textContent = '';
            
            // Hide main status bar after 3 seconds if not running
            setTimeout(() => {
                if (sseRunBtn.disabled === false) {
                    sseStatusBar.classList.add('hidden');
                }
            }, 3000);
        }
    }

    function startSseLogStream() {
        if (sseEventSource) sseEventSource.close();
        sseTerminal.innerHTML = '';
        addSseTerminalLog('>>> Starting SkySolverEngine (SSE) log stream...', 'system');
        
        sseEventSource = new EventSource('/api/sse/logs');
        sseEventSource.onmessage = (event) => {
            if (event.data === '[Process Finished]') {
                setSseStatus(false, 'Finished');
                sseEventSource.close();
                addSseTerminalLog('--- SSE Execution Finished ---', 'system');
                loadLogsBtn.click();
            } else {
                addSseTerminalLog(event.data);
                
                // Parse processing DNG/RAW filename
                const cleanLine = stripAnsi(event.data);
                const match = cleanLine.match(/Processing\s+(?:Latest:\s+)?\[([^\]]+)\]/i);
                if (match && match[1]) {
                    sseStatusFile.textContent = `File: ${match[1]}`;
                }
            }
        };
        sseEventSource.onerror = () => {
            setSseStatus(false, 'Stopped / Error');
            sseEventSource.close();
            addSseTerminalLog('>>> Connection lost or SSE process ended.', 'error');
            loadLogsBtn.click();
        };
    }

    sseRunBtn.onclick = async () => {
        const path = logPathInput.value.trim();
        if (!path) {
            alert('Please specify a valid Log Folder first.');
            return;
        }

        const formData = new FormData();
        formData.append('target_path', path);
        formData.append('target_type', sseTargetSelect.value);
        formData.append('allsky', sseAllskyCheckbox.checked);
        formData.append('force', sseForceCheckbox.checked);

        if (sseTargetSelect.value === 'session') {
            if (!selectedSessionId) {
                alert('No session selected.');
                return;
            }
            formData.append('session_id', selectedSessionId);
        } else if (sseTargetSelect.value === 'file') {
            if (!selectedFileName) {
                alert('No file selected.');
                return;
            }
            formData.append('file_name', selectedFileName);
        }

        sseConsoleModal.classList.remove('hidden');
        setSseStatus(true);
        addSseTerminalLog('>>> Starting SSE solver...', 'system');

        try {
            const resp = await fetch('/api/sse/start', {
                method: 'POST',
                body: formData
            });
            if (resp.ok) {
                startSseLogStream();
            } else {
                const err = await resp.json();
                addSseTerminalLog(`ERROR starting SSE: ${err.detail}`, 'error');
                setSseStatus(false);
                sseModalStatus.textContent = 'Failed';
                sseModalStatus.style.color = 'var(--accent-red)';
            }
        } catch (e) {
            addSseTerminalLog(`Fetch Error: ${e.message}`, 'error');
            setSseStatus(false);
            sseModalStatus.textContent = 'Failed';
            sseModalStatus.style.color = 'var(--accent-red)';
        }
    };

    sseStopBtn.onclick = async () => {
        try {
            addSseTerminalLog('>>> Stopping SSE solver...', 'system');
            const resp = await fetch('/api/sse/stop', { method: 'POST' });
            if (resp.ok) {
                addSseTerminalLog('>>> Stop signal sent.', 'system');
            }
        } catch (e) {
            addSseTerminalLog(`Stop Error: ${e.message}`, 'error');
        }
    };

    closeSseModalBtn.onclick = () => sseConsoleModal.classList.add('hidden');
    sseModalCloseBtn.onclick = () => sseConsoleModal.classList.add('hidden');

    // --- Init ---
    loadGuiConfig();
    (async () => {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            if (data.status === 'running') { setShutterStatus(true); startShutterLogStream(); }
        } catch (e) {}
        try {
            const resp = await fetch('/api/sse/status');
            const data = await resp.json();
            if (data.status === 'running') {
                sseConsoleModal.classList.remove('hidden');
                setSseStatus(true);
                startSseLogStream();
            }
        } catch (e) {}
    })();
});

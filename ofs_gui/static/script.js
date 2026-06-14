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

        // Reset Starflux targets
        if (window.sfTargetSessionOpt) {
            window.sfTargetSessionOpt.disabled = true;
            window.sfTargetFileOpt.disabled = true;
            window.sfTargetSelect.value = 'folder';
        }

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
                if (window.sfTargetSessionOpt) {
                    window.sfTargetSessionOpt.disabled = false;
                    if (window.sfTargetSelect.value === 'folder') {
                        window.sfTargetSelect.value = 'session';
                    }
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
                if (window.sfTargetFileOpt) {
                    window.sfTargetFileOpt.disabled = false;
                }
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


    // =========================================================================
    // STARFLUX RUNNER LOGIC
    // =========================================================================
    const sfTargetSelect = document.getElementById('sf-target');
    const sfTargetSessionOpt = document.getElementById('sf-target-session-opt');
    const sfTargetFileOpt = document.getElementById('sf-target-file-opt');
    const sfForceCheckbox = document.getElementById('sf-force');
    const sfPlotCheckbox = document.getElementById('sf-plot');
    const sfSnrInput = document.getElementById('sf-snr');
    const sfTopStarsInput = document.getElementById('sf-top-stars');
    const sfRunBtn = document.getElementById('sf-run-btn');
    const sfStopBtn = document.getElementById('sf-stop-btn');
    const sfConsoleModal = document.getElementById('sf-console-modal');
    const closeSfModalBtn = document.getElementById('close-sf-modal-btn');
    const sfModalCloseBtn = document.getElementById('sf-modal-close-btn');
    const sfTerminal = document.getElementById('sf-terminal');
    const sfModalStatus = document.getElementById('sf-modal-status');
    
    // Status bar elements
    const sfStatusBar = document.getElementById('sf-status-bar');
    const sfStatusText = document.getElementById('sf-status-text');
    const sfStatusFile = document.getElementById('sf-status-file');

    // Expose window references for target resetting logic
    window.sfTargetSelect = sfTargetSelect;
    window.sfTargetSessionOpt = sfTargetSessionOpt;
    window.sfTargetFileOpt = sfTargetFileOpt;

    let sfEventSource = null;

    function addSfTerminalLog(text, type = '') {
        const cleanText = stripAnsi(text).trim();
        if (!cleanText) return;
        const div = document.createElement('div');
        div.className = `log-line ${type}`;
        if (cleanText.toLowerCase().includes('success') || cleanText.toLowerCase().includes('finished')) div.classList.add('shutter-on');
        if (cleanText.toLowerCase().includes('error') || cleanText.toLowerCase().includes('failed')) div.classList.add('error');
        div.textContent = cleanText;
        sfTerminal.appendChild(div);
        sfTerminal.scrollTop = sfTerminal.scrollHeight;
    }

    function setSfStatus(running, endStatus = '') {
        if (running) {
            sfRunBtn.disabled = true;
            sfStopBtn.disabled = false;
            sfModalStatus.textContent = 'Running...';
            sfModalStatus.style.color = 'var(--accent-blue)';
            
            // Show main window status bar
            sfStatusBar.classList.remove('hidden');
            sfStatusText.textContent = 'Starflux Running...';
            sfStatusText.style.color = 'var(--accent-gold)';
            sfStatusFile.textContent = 'Starting...';
            const spinner = sfStatusBar.querySelector('.sse-spinner');
            if (spinner) spinner.style.display = 'inline-block';
        } else {
            sfRunBtn.disabled = false;
            sfStopBtn.disabled = true;
            
            const label = endStatus || 'Idle';
            sfModalStatus.textContent = label;
            
            if (label.toLowerCase().includes('finished') || label.toLowerCase().includes('success')) {
                sfModalStatus.style.color = '#00ff88';
                sfStatusText.textContent = 'Starflux Finished';
                sfStatusText.style.color = '#00ff88';
            } else if (label.toLowerCase().includes('stopped') || label.toLowerCase().includes('error') || label.toLowerCase().includes('failed')) {
                sfModalStatus.style.color = 'var(--accent-red)';
                sfStatusText.textContent = label;
                sfStatusText.style.color = 'var(--accent-red)';
            } else {
                sfModalStatus.style.color = 'var(--text-dim)';
                sfStatusText.textContent = 'Starflux Idle';
                sfStatusText.style.color = 'var(--text-dim)';
            }
            
            const spinner = sfStatusBar.querySelector('.sse-spinner');
            if (spinner) spinner.style.display = 'none';
            sfStatusFile.textContent = '';
            
            // Hide main status bar after 3 seconds if not running
            setTimeout(() => {
                if (sfRunBtn.disabled === false) {
                    sfStatusBar.classList.add('hidden');
                }
            }, 3000);
        }
    }

    function startSfLogStream() {
        if (sfEventSource) sfEventSource.close();
        sfTerminal.innerHTML = '';
        addSfTerminalLog('>>> Starting Starflux log stream...', 'system');
        
        sfEventSource = new EventSource('/api/starflux/logs');
        sfEventSource.onmessage = (event) => {
            if (event.data === '[Process Finished]') {
                setSfStatus(false, 'Finished');
                sfEventSource.close();
                addSfTerminalLog('--- Starflux Execution Finished ---', 'system');
                loadLogsBtn.click();
            } else {
                addSfTerminalLog(event.data);
                
                // Parse processing filename
                const cleanLine = stripAnsi(event.data);
                const match = cleanLine.match(/\[Processing\]\s+([^\.]+)\.(?:dng|raw|fits|fit|fts)/i);
                if (match && match[1]) {
                    sfStatusFile.textContent = `File: ${match[1]}`;
                }
            }
        };
        sfEventSource.onerror = () => {
            setSfStatus(false, 'Stopped / Error');
            sfEventSource.close();
            addSfTerminalLog('>>> Connection lost or Starflux process ended.', 'error');
            loadLogsBtn.click();
        };
    }

    sfRunBtn.onclick = async () => {
        const path = logPathInput.value.trim();
        if (!path) {
            alert('Please specify a valid Log Folder first.');
            return;
        }

        const formData = new FormData();
        formData.append('target_path', path);
        formData.append('target_type', sfTargetSelect.value);
        formData.append('force', sfForceCheckbox.checked);
        formData.append('plot', sfPlotCheckbox.checked);
        formData.append('snr', sfSnrInput.value);
        formData.append('top_stars', sfTopStarsInput.value);

        if (sfTargetSelect.value === 'session') {
            if (!selectedSessionId) {
                alert('No session selected.');
                return;
            }
            formData.append('session_id', selectedSessionId);
        } else if (sfTargetSelect.value === 'file') {
            if (!selectedFileName) {
                alert('No file selected.');
                return;
            }
            formData.append('file_name', selectedFileName);
        }

        sfConsoleModal.classList.remove('hidden');
        setSfStatus(true);
        addSfTerminalLog('>>> Starting Starflux analyzer...', 'system');

        try {
            const resp = await fetch('/api/starflux/start', {
                method: 'POST',
                body: formData
            });
            if (resp.ok) {
                startSfLogStream();
            } else {
                const err = await resp.json();
                addSfTerminalLog(`ERROR starting Starflux: ${err.detail}`, 'error');
                setSfStatus(false);
                sfModalStatus.textContent = 'Failed';
                sfModalStatus.style.color = 'var(--accent-red)';
            }
        } catch (e) {
            addSfTerminalLog(`Fetch Error: ${e.message}`, 'error');
            setSfStatus(false);
            sfModalStatus.textContent = 'Failed';
            sfModalStatus.style.color = 'var(--accent-red)';
        }
    };

    sfStopBtn.onclick = async () => {
        try {
            addSfTerminalLog('>>> Stopping Starflux solver...', 'system');
            const resp = await fetch('/api/starflux/stop', { method: 'POST' });
            if (resp.ok) {
                addSfTerminalLog('>>> Stop signal sent.', 'system');
            }
        } catch (e) {
            addSfTerminalLog(`Stop Error: ${e.message}`, 'error');
        }
    };

    closeSfModalBtn.onclick = () => sfConsoleModal.classList.add('hidden');
    sfModalCloseBtn.onclick = () => sfConsoleModal.classList.add('hidden');


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
        try {
            const resp = await fetch('/api/starforge/status');
            const data = await resp.json();
            if (data.status === 'running') {
                sfgConsoleModal.classList.remove('hidden');
                setSfgStatus(true);
                startSfgLogStream();
            }
        } catch (e) {}
    })();

    // =========================================================================
    // STARFORGE LOGIC
    // =========================================================================
    const sfgMode = document.getElementById('sfg-mode');
    const sfgMethod = document.getElementById('sfg-method');
    const sfgThreshold = document.getElementById('sfg-threshold');
    const sfgOut = document.getElementById('sfg-out');
    const sfgOutDir = document.getElementById('sfg-out-dir');
    const sfgLimit = document.getElementById('sfg-limit');
    const sfgUseFlat = document.getElementById('sfg-use-flat');
    const sfgFlatFields = document.getElementById('sfg-flat-fields');
    const sfgFlatDir = document.getElementById('sfg-flat-dir');
    const sfgFlatSession = document.getElementById('sfg-flat-session');
    const sfgUseDark = document.getElementById('sfg-use-dark');
    const sfgDarkFields = document.getElementById('sfg-dark-fields');
    const sfgDarkDir = document.getElementById('sfg-dark-dir');
    const sfgDarkSession = document.getElementById('sfg-dark-session');
    const sfgRunBtn = document.getElementById('sfg-run-btn');
    const sfgStopBtn = document.getElementById('sfg-stop-btn');
    const sfgLoadLogsBtn = document.getElementById('sfg-load-logs-btn');
    const sfgSessionList = document.getElementById('sfg-session-list');
    const sfgFileList = document.getElementById('sfg-file-list');
    const sfgSessionsSelectAll = document.getElementById('sfg-sessions-select-all');
    const sfgSessionsSelectNone = document.getElementById('sfg-sessions-select-none');
    const sfgFilesSelectAll = document.getElementById('sfg-files-select-all');
    const sfgFilesSelectNone = document.getElementById('sfg-files-select-none');
    const sfgHistogramCanvas = document.getElementById('sfg-histogram-canvas');
    const sfgHistStats = document.getElementById('sfg-hist-stats');
    const sfgImagePreviewContainer = document.getElementById('sfg-image-preview-container');
    const sfgImageInfo = document.getElementById('sfg-image-info');
    const sfgReportsContainer = document.getElementById('sfg-reports-container');
    const sfgReportMd = document.getElementById('sfg-report-md');
    const sfgReportHtml = document.getElementById('sfg-report-html');

    // Modals
    const sfgConsoleModal = document.getElementById('sfg-console-modal');
    const closeSfgModalBtn = document.getElementById('close-sfg-modal-btn');
    const sfgModalCloseBtn = document.getElementById('sfg-modal-close-btn');
    const sfgTerminal = document.getElementById('sfg-terminal');
    const sfgModalStatus = document.getElementById('sfg-modal-status');
    const sfgStatusBar = document.getElementById('sfg-status-bar');
    const sfgStatusText = document.getElementById('sfg-status-text');
    const sfgStatusFile = document.getElementById('sfg-status-file');

    let sfgSessionsMap = new Map();
    let selectedSfgSessions = new Set();
    let selectedSfgFiles = new Set();
    let sfgEventSource = null;
    let sfgResultFitsPath = '';
    let sfgResultMdPath = '';
    let sfgResultHtmlPath = '';

    // Folder Pickers
    initFolderPicker('browse-sfg-out-dir-btn', 'sfg-out-dir');
    initFolderPicker('browse-sfg-flat-dir-btn', 'sfg-flat-dir');
    initFolderPicker('browse-sfg-dark-dir-btn', 'sfg-dark-dir');
    initFolderPicker('browse-sfg-log-path-btn', 'sfg-log-path');

    // Toggles
    const toggleFlatFields = () => {
        sfgFlatFields.classList.toggle('hidden', !sfgUseFlat.checked);
    };
    const toggleDarkFields = () => {
        sfgDarkFields.classList.toggle('hidden', !sfgUseDark.checked);
    };
    sfgUseFlat.onchange = toggleFlatFields;
    sfgUseDark.onchange = toggleDarkFields;
    toggleFlatFields();
    toggleDarkFields();

    // Load Logs
    sfgLoadLogsBtn.onclick = async () => {
        const path = document.getElementById('sfg-log-path').value.trim();
        if (!path) return;
        sfgSessionList.innerHTML = '<div class="placeholder">Loading...</div>';
        sfgFileList.innerHTML = '<div class="placeholder">Waiting...</div>';
        selectedSfgSessions.clear();
        selectedSfgFiles.clear();
        sfgSessionsMap.clear();
        
        try {
            const resp = await fetch(`/api/logs/browse?path=${encodeURIComponent(path)}`);
            if (!resp.ok) throw new Error((await resp.json()).detail || 'Failed to load logs');
            const data = await resp.json();
            data.forEach(record => {
                const sid = record.session_id || 'Unknown';
                if (!sfgSessionsMap.has(sid)) sfgSessionsMap.set(sid, []);
                sfgSessionsMap.get(sid).push(record);
            });
            renderSfgSessions();
        } catch (e) {
            sfgSessionList.innerHTML = `<div class="placeholder error">Error: ${e.message}</div>`;
        }
    };

    function renderSfgSessions() {
        sfgSessionList.innerHTML = '';
        if (sfgSessionsMap.size === 0) {
            sfgSessionList.innerHTML = '<div class="placeholder">No sessions found</div>';
            return;
        }
        const sortedIds = Array.from(sfgSessionsMap.keys()).sort().reverse();
        sortedIds.forEach(sid => {
            const records = sfgSessionsMap.get(sid);
            const obj = records[0]?.objective || 'N/A';
            const item = document.createElement('div');
            item.className = 'list-item';
            
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.id = `sfg-sess-cb-${sid}`;
            cb.checked = selectedSfgSessions.has(sid);
            cb.onclick = (e) => e.stopPropagation();
            cb.onchange = () => {
                if (cb.checked) selectedSfgSessions.add(sid);
                else selectedSfgSessions.delete(sid);
                updateSfgFiles();
            };

            const label = document.createElement('label');
            label.className = 'item-label';
            label.htmlFor = cb.id;
            label.innerHTML = `<span class="session-name">${sid}</span><span class="session-obj">${obj}</span>`;

            item.appendChild(cb);
            item.appendChild(label);
            sfgSessionList.appendChild(item);
        });
        updateSfgFiles();
    }

    function updateSfgFiles() {
        sfgFileList.innerHTML = '';
        const selectedRecords = [];
        selectedSfgSessions.forEach(sid => {
            const records = sfgSessionsMap.get(sid) || [];
            selectedRecords.push(...records);
        });

        if (selectedRecords.length === 0) {
            sfgFileList.innerHTML = '<div class="placeholder">Select sessions first</div>';
            selectedSfgFiles.clear();
            drawHistogram();
            return;
        }

        selectedRecords.sort((a, b) => {
            const ta = a.record?.meta?.iso_timestamp || '';
            const tb = b.record?.meta?.iso_timestamp || '';
            return ta.localeCompare(tb);
        });

        selectedSfgFiles.clear();

        selectedRecords.forEach(record => {
            const fileName = record.record?.file?.name || 'Unknown';
            const filePath = record.record?.file?.path || '';
            const fullPath = filePath ? `${filePath}/${fileName}` : fileName;
            const time = formatTime(record.record?.meta?.iso_timestamp);
            
            const item = document.createElement('div');
            item.className = 'list-item';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.id = `sfg-file-cb-${fileName}`;
            cb.checked = true; // default select all
            selectedSfgFiles.add(fullPath);
            cb.onclick = (e) => e.stopPropagation();
            cb.onchange = () => {
                if (cb.checked) selectedSfgFiles.add(fullPath);
                else selectedSfgFiles.delete(fullPath);
                drawHistogram();
            };

            const label = document.createElement('label');
            label.className = 'item-label';
            label.htmlFor = cb.id;
            
            const q = record.analysis?.SF?.quality || record.analysis?.quality || record.record?.analysis?.quality;
            const ellVal = q?.sf_ell_med;
            const ellText = ellVal !== undefined ? `Ell: ${ellVal.toFixed(3)}` : 'No Quality';

            label.innerHTML = `<span class="file-name">${fileName}</span><span class="file-time">${ellText} | ${time}</span>`;

            item.appendChild(cb);
            item.appendChild(label);
            sfgFileList.appendChild(item);
        });
        drawHistogram();
    }

    sfgSessionsSelectAll.onclick = (e) => {
        e.preventDefault();
        const checkboxes = sfgSessionList.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = true;
            const sid = cb.id.replace('sfg-sess-cb-', '');
            selectedSfgSessions.add(sid);
        });
        updateSfgFiles();
    };
    sfgSessionsSelectNone.onclick = (e) => {
        e.preventDefault();
        const checkboxes = sfgSessionList.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = false;
        });
        selectedSfgSessions.clear();
        updateSfgFiles();
    };

    sfgFilesSelectAll.onclick = (e) => {
        e.preventDefault();
        const checkboxes = sfgFileList.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = true;
            const fileName = cb.id.replace('sfg-file-cb-', '');
            for (const records of sfgSessionsMap.values()) {
                const r = records.find(x => x.record?.file?.name === fileName);
                if (r) {
                    const fullPath = r.record?.file?.path ? `${r.record.file.path}/${fileName}` : fileName;
                    selectedSfgFiles.add(fullPath);
                    break;
                }
            }
        });
        drawHistogram();
    };

    sfgFilesSelectNone.onclick = (e) => {
        e.preventDefault();
        const checkboxes = sfgFileList.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = false;
        });
        selectedSfgFiles.clear();
        drawHistogram();
    };

    // Draw Histogram
    function drawHistogram() {
        const ctx = sfgHistogramCanvas.getContext('2d');
        const width = sfgHistogramCanvas.clientWidth;
        const height = sfgHistogramCanvas.clientHeight;
        sfgHistogramCanvas.width = width;
        sfgHistogramCanvas.height = height;
        ctx.clearRect(0, 0, width, height);

        const values = [];
        const checkedCheckboxes = sfgFileList.querySelectorAll('input[type="checkbox"]:checked');
        checkedCheckboxes.forEach(cb => {
            const fileName = cb.id.replace('sfg-file-cb-', '');
            for (const records of sfgSessionsMap.values()) {
                const r = records.find(x => x.record?.file?.name === fileName);
                if (r) {
                    const q = r.analysis?.SF?.quality || r.analysis?.quality || r.record?.analysis?.quality;
                    const ellVal = q?.sf_ell_med;
                    if (ellVal !== undefined && ellVal !== null) {
                        values.push(ellVal);
                    }
                    break;
                }
            }
        });

        if (values.length === 0) {
            sfgHistStats.textContent = 'No data';
            ctx.fillStyle = '#959da5';
            ctx.font = '11px Inter';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('No ellipticity data available', width / 2, height / 2);
            return;
        }

        const maxVal = Math.max(...values, 0.4);
        const rangeMax = maxVal > 0.5 ? 1.0 : 0.5;
        const rangeMin = 0.0;
        
        const numBins = 20;
        const bins = new Array(numBins).fill(0);
        values.forEach(v => {
            let binIdx = Math.floor(((v - rangeMin) / (rangeMax - rangeMin)) * numBins);
            if (binIdx >= numBins) binIdx = numBins - 1;
            if (binIdx < 0) binIdx = 0;
            bins[binIdx]++;
        });

        const maxBinCount = Math.max(...bins, 1);
        const paddingLeft = 25;
        const paddingRight = 10;
        const paddingTop = 15;
        const paddingBottom = 20;

        const chartWidth = width - paddingLeft - paddingRight;
        const chartHeight = height - paddingTop - paddingBottom;
        const binWidth = chartWidth / numBins;
        const threshold = parseFloat(sfgThreshold.value) || 0.20;

        bins.forEach((count, i) => {
            const binCenter = rangeMin + ((i + 0.5) / numBins) * (rangeMax - rangeMin);
            const x = paddingLeft + i * binWidth;
            const barHeight = (count / maxBinCount) * chartHeight;
            const y = height - paddingBottom - barHeight;

            if (binCenter <= threshold) {
                ctx.fillStyle = 'rgba(0, 255, 136, 0.4)';
                ctx.strokeStyle = 'rgba(0, 255, 136, 0.8)';
            } else {
                ctx.fillStyle = 'rgba(255, 71, 87, 0.2)';
                ctx.strokeStyle = 'rgba(255, 71, 87, 0.6)';
            }

            ctx.fillRect(x + 1, y, binWidth - 2, barHeight);
            ctx.strokeRect(x + 1, y, binWidth - 2, barHeight);
        });

        // Threshold Line
        const thresholdX = paddingLeft + ((threshold - rangeMin) / (rangeMax - rangeMin)) * chartWidth;
        if (thresholdX >= paddingLeft && thresholdX <= paddingLeft + chartWidth) {
            ctx.beginPath();
            ctx.strokeStyle = '#c9a063';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([3, 3]);
            ctx.moveTo(thresholdX, paddingTop);
            ctx.lineTo(thresholdX, height - paddingBottom);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.fillStyle = '#c9a063';
            ctx.font = '9px JetBrains Mono';
            ctx.textAlign = 'center';
            ctx.fillText(`TH: ${threshold.toFixed(2)}`, thresholdX, paddingTop - 4);
        }

        // Axes
        ctx.strokeStyle = 'var(--glass-border)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(paddingLeft, height - paddingBottom);
        ctx.lineTo(width - paddingRight, height - paddingBottom);
        ctx.moveTo(paddingLeft, paddingTop);
        ctx.lineTo(paddingLeft, height - paddingBottom);
        ctx.stroke();

        ctx.fillStyle = 'var(--text-dim)';
        ctx.font = '9px JetBrains Mono';
        ctx.textAlign = 'center';
        ctx.fillText(rangeMin.toFixed(1), paddingLeft, height - paddingBottom + 12);
        ctx.fillText((rangeMax / 2).toFixed(2), paddingLeft + chartWidth / 2, height - paddingBottom + 12);
        ctx.fillText(rangeMax.toFixed(1), width - paddingRight, height - paddingBottom + 12);

        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText('0', paddingLeft - 5, height - paddingBottom);
        ctx.fillText(maxBinCount.toString(), paddingLeft - 5, paddingTop);

        const numStacked = values.filter(v => v <= threshold).length;
        const percentage = values.length > 0 ? ((numStacked / values.length) * 100).toFixed(0) : 0;
        sfgHistStats.textContent = `Stacking: ${numStacked}/${values.length} (${percentage}%)`;
    }

    sfgThreshold.oninput = () => {
        drawHistogram();
    };

    sfgHistogramCanvas.onclick = (e) => {
        const rect = sfgHistogramCanvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        
        const paddingLeft = 25;
        const paddingRight = 10;
        const chartWidth = sfgHistogramCanvas.width - paddingLeft - paddingRight;

        const values = [];
        const checkedCheckboxes = sfgFileList.querySelectorAll('input[type="checkbox"]:checked');
        checkedCheckboxes.forEach(cb => {
            const fileName = cb.id.replace('sfg-file-cb-', '');
            for (const records of sfgSessionsMap.values()) {
                const r = records.find(x => x.record?.file?.name === fileName);
                if (r) {
                    const q = r.analysis?.SF?.quality || r.analysis?.quality || r.record?.analysis?.quality;
                    const ellVal = q?.sf_ell_med;
                    if (ellVal !== undefined && ellVal !== null) {
                        values.push(ellVal);
                    }
                    break;
                }
            }
        });
        const maxVal = values.length > 0 ? Math.max(...values, 0.4) : 0.4;
        const rangeMax = maxVal > 0.5 ? 1.0 : 0.5;
        const rangeMin = 0.0;

        if (clickX >= paddingLeft && clickX <= paddingLeft + chartWidth) {
            const ratio = (clickX - paddingLeft) / chartWidth;
            const newThreshold = rangeMin + ratio * (rangeMax - rangeMin);
            sfgThreshold.value = newThreshold.toFixed(2);
            drawHistogram();
        }
    };

    // Subprocess execution & monitoring
    function setSfgStatus(running, endStatus = '') {
        if (running) {
            sfgRunBtn.disabled = true;
            sfgStopBtn.disabled = false;
            sfgModalStatus.textContent = 'Running...';
            sfgModalStatus.style.color = 'var(--accent-blue)';
            
            sfgStatusBar.classList.remove('hidden');
            sfgStatusText.textContent = 'StarForge Stacking...';
            sfgStatusText.style.color = '#00ff88';
            sfgStatusFile.textContent = 'Starting...';
            const spinner = sfgStatusBar.querySelector('.sse-spinner');
            if (spinner) spinner.style.display = 'inline-block';
        } else {
            sfgRunBtn.disabled = false;
            sfgStopBtn.disabled = true;
            
            const label = endStatus || 'Idle';
            sfgModalStatus.textContent = label;
            
            if (label.toLowerCase().includes('finished') || label.toLowerCase().includes('success')) {
                sfgModalStatus.style.color = '#00ff88';
                sfgStatusText.textContent = 'Stacking Finished';
                sfgStatusText.style.color = '#00ff88';
            } else if (label.toLowerCase().includes('stopped') || label.toLowerCase().includes('error') || label.toLowerCase().includes('failed')) {
                sfgModalStatus.style.color = 'var(--accent-red)';
                sfgStatusText.textContent = label;
                sfgStatusText.style.color = 'var(--accent-red)';
            } else {
                sfgModalStatus.style.color = 'var(--text-dim)';
                sfgStatusText.textContent = 'StarForge Idle';
                sfgStatusText.style.color = 'var(--text-dim)';
            }
            
            const spinner = sfgStatusBar.querySelector('.sse-spinner');
            if (spinner) spinner.style.display = 'none';
            sfgStatusFile.textContent = '';
            
            setTimeout(() => {
                if (sfgRunBtn.disabled === false) {
                    sfgStatusBar.classList.add('hidden');
                }
            }, 3000);
        }
    }

    function addSfgTerminalLog(text, type = '') {
        const cleanText = stripAnsi(text).trim();
        if (!cleanText) return;
        const div = document.createElement('div');
        div.className = `log-line ${type}`;
        if (cleanText.toLowerCase().includes('success') || cleanText.toLowerCase().includes('saved') || cleanText.toLowerCase().includes('finished')) div.classList.add('shutter-on');
        if (cleanText.toLowerCase().includes('error') || cleanText.toLowerCase().includes('failed') || cleanText.toLowerCase().includes('skip')) div.classList.add('error');
        div.textContent = cleanText;
        sfgTerminal.appendChild(div);
        sfgTerminal.scrollTop = sfgTerminal.scrollHeight;
    }

    function startSfgLogStream() {
        if (sfgEventSource) sfgEventSource.close();
        sfgTerminal.innerHTML = '';
        addSfgTerminalLog('>>> Starting StarForge Stacker log stream...', 'system');
        
        sfgResultFitsPath = '';
        sfgResultMdPath = '';
        sfgResultHtmlPath = '';
        sfgReportsContainer.classList.add('hidden');

        sfgEventSource = new EventSource('/api/starforge/logs');
        sfgEventSource.onmessage = (event) => {
            if (event.data === '[Process Finished]') {
                setSfgStatus(false, 'Finished');
                sfgEventSource.close();
                addSfgTerminalLog('--- StarForge Stack Finished ---', 'system');
                
                // Show result preview if we captured a fits path
                if (sfgResultFitsPath) {
                    loadSfgFitsPreview(sfgResultFitsPath);
                }
                if (sfgResultMdPath || sfgResultHtmlPath) {
                    sfgReportsContainer.classList.remove('hidden');
                    if (sfgResultMdPath) {
                        sfgReportMd.href = `/api/logs/image?path=${encodeURIComponent(sfgResultMdPath)}`;
                        sfgReportMd.style.display = 'inline-block';
                    } else {
                        sfgReportMd.style.display = 'none';
                    }
                    if (sfgResultHtmlPath) {
                        sfgReportHtml.href = `/api/logs/image?path=${encodeURIComponent(sfgResultHtmlPath)}`;
                        sfgReportHtml.style.display = 'inline-block';
                    } else {
                        sfgReportHtml.style.display = 'none';
                    }
                }
            } else {
                addSfgTerminalLog(event.data);
                
                const cleanLine = stripAnsi(event.data);
                
                // Parse processing status
                if (cleanLine.includes('[Stack-Logic] Processing:')) {
                    sfgStatusFile.textContent = cleanLine.trim();
                } else if (cleanLine.includes('Processing:')) {
                    sfgStatusFile.textContent = cleanLine.trim();
                }
                
                // Parse FITS saving
                const fitsMatch = cleanLine.match(/\[Success\]\s+Master\s+frame\s+saved\s+to:\s+(.+)/i);
                if (fitsMatch && fitsMatch[1]) {
                    sfgResultFitsPath = fitsMatch[1].trim();
                }

                // Parse MD Report
                const mdMatch = cleanLine.match(/\[Report\]\s+Saved\s+Markdown:\s+(.+)/i);
                if (mdMatch && mdMatch[1]) {
                    sfgResultMdPath = mdMatch[1].trim();
                }

                // Parse HTML Report
                const htmlMatch = cleanLine.match(/\[Report\]\s+Saved\s+HTML\s+\(full\):\s+(.+)/i);
                if (htmlMatch && htmlMatch[1]) {
                    sfgResultHtmlPath = htmlMatch[1].trim();
                }
            }
        };
        sfgEventSource.onerror = () => {
            setSfgStatus(false, 'Stopped / Error');
            sfgEventSource.close();
            addSfgTerminalLog('>>> Connection lost or StarForge process ended.', 'error');
        };
    }

    sfgRunBtn.onclick = async () => {
        const checkedCheckboxes = sfgFileList.querySelectorAll('input[type="checkbox"]:checked');
        if (checkedCheckboxes.length === 0) {
            alert('Please select files to stack first.');
            return;
        }

        // Collect inputs paths
        const inputFiles = [];
        checkedCheckboxes.forEach(cb => {
            const fileName = cb.id.replace('sfg-file-cb-', '');
            for (const records of sfgSessionsMap.values()) {
                const r = records.find(x => x.record?.file?.name === fileName);
                if (r) {
                    const fullPath = r.record?.file?.path ? `${r.record.file.path}/${fileName}` : fileName;
                    inputFiles.push(fullPath);
                    break;
                }
            }
        });

        const formData = new FormData();
        formData.append('inputs', inputFiles.join(','));
        formData.append('mode', sfgMode.value);
        formData.append('method', sfgMethod.value);
        formData.append('threshold', sfgThreshold.value);
        formData.append('out', sfgOut.value);
        formData.append('out_dir', sfgOutDir.value);
        formData.append('limit', sfgLimit.value);
        
        formData.append('use_flat', sfgUseFlat.checked ? 'true' : 'false');
        if (sfgUseFlat.checked) {
            formData.append('flat_dir', sfgFlatDir.value);
            formData.append('flat_session', sfgFlatSession.value);
        }

        formData.append('use_dark', sfgUseDark.checked ? 'true' : 'false');
        if (sfgUseDark.checked) {
            formData.append('dark_dir', sfgDarkDir.value);
            formData.append('dark_session', sfgDarkSession.value);
        }

        sfgConsoleModal.classList.remove('hidden');
        setSfgStatus(true);
        addSfgTerminalLog('>>> Starting StarForge stacker...', 'system');

        try {
            const resp = await fetch('/api/starforge/start', {
                method: 'POST',
                body: formData
            });
            if (resp.ok) {
                startSfgLogStream();
            } else {
                const err = await resp.json();
                addSfgTerminalLog(`ERROR starting StarForge: ${err.detail}`, 'error');
                setSfgStatus(false);
                sfgModalStatus.textContent = 'Failed';
                sfgModalStatus.style.color = 'var(--accent-red)';
            }
        } catch (e) {
            addSfgTerminalLog(`Fetch Error: ${e.message}`, 'error');
            setSfgStatus(false);
            sfgModalStatus.textContent = 'Failed';
            sfgModalStatus.style.color = 'var(--accent-red)';
        }
    };

    sfgStopBtn.onclick = async () => {
        try {
            addSfgTerminalLog('>>> Stopping StarForge stacker...', 'system');
            const resp = await fetch('/api/starforge/stop', { method: 'POST' });
            if (resp.ok) {
                addSfgTerminalLog('>>> Stop signal sent.', 'system');
            }
        } catch (e) {
            addSfgTerminalLog(`Stop Error: ${e.message}`, 'error');
        }
    };

    closeSfgModalBtn.onclick = () => sfgConsoleModal.classList.add('hidden');
    sfgModalCloseBtn.onclick = () => sfgConsoleModal.classList.add('hidden');

    function loadSfgFitsPreview(fitsPath) {
        sfgImagePreviewContainer.innerHTML = '<div class="placeholder">Loading stacked preview...</div>';
        const img = document.createElement('img');
        img.src = `/api/fits/preview?path=${encodeURIComponent(fitsPath)}`;
        img.onerror = () => {
            sfgImagePreviewContainer.innerHTML = '<div class="no-preview">Preview not available</div>';
        };
        img.onload = () => {
            sfgImagePreviewContainer.innerHTML = '';
            sfgImagePreviewContainer.appendChild(img);
        };
        
        // Setup click-to-zoom on stacked preview
        sfgImagePreviewContainer.onclick = () => {
            if (img.src) {
                enlargedImage.src = img.src;
                imageModal.classList.remove('hidden');
                resetZoomState();
            }
        };

        sfgImageInfo.textContent = `Stacked FITS File: ${fitsPath.split('/').pop()}`;
    }
    
    // Trigger initial status check for StarForge
    (async () => {
        try {
            const resp = await fetch('/api/starforge/status');
            const data = await resp.json();
            if (data.status === 'running') {
                sfgConsoleModal.classList.remove('hidden');
                setSfgStatus(true);
                startSfgLogStream();
            }
        } catch (e) {}
    })();
});


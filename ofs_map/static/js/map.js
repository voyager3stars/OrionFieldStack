// map.js
document.addEventListener("DOMContentLoaded", () => {
    // Initialize map
    const map = L.map('map', { minZoom: 2 }).setView([35.65, 139.75], 5); // Default to Japan roughly, zoom 5

    // Add local tile layer
    // errorTileUrl is handled by backend returning a gray image instead of 404,
    // but just in case, we can also provide a fallback or rely on backend.
    const tileLayer = L.tileLayer('/tiles/{z}/{x}/{y}.png', {
        minZoom: 2,
        maxZoom: 17,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    // --- Satellite Sub-Map Initialization ---
    const satMap = L.map('sat-map', { 
        minZoom: 2, 
        maxZoom: 4,
        zoomControl: true,
        attributionControl: false
    }).setView([35.65, 139.75], 2);
    
    // Use the same tile server, but limit zoom
    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
        minZoom: 2,
        maxZoom: 4
    }).addTo(satMap);
    // ----------------------------------------

    // --- Leaflet Draw for Area Selection ---
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    
    const drawControl = new L.Control.Draw({
        draw: {
            polyline: false,
            polygon: false,
            circle: false,
            circlemarker: false,
            marker: false,
            rectangle: {
                shapeOptions: {
                    color: '#FF9800',
                    weight: 2
                }
            }
        },
        edit: false
    });
    map.addControl(drawControl);
    
    map.on(L.Draw.Event.CREATED, function (e) {
        const layer = e.layer;
        drawnItems.clearLayers();
        drawnItems.addLayer(layer);
        
        // Open modal automatically with the drawn bounds
        currentBounds = layer.getBounds();
        const modal = document.getElementById('download-modal');
        if (modal) {
            modal.style.display = "block";
            document.getElementById('download-status').textContent = '';
            const currentZoom = map.getZoom();
            const zoomSelect = document.getElementById('max-zoom-select');
            const zoomValDisplay = document.getElementById('zoom-val-display');
            if (zoomSelect) {
                zoomSelect.value = currentZoom;
                zoomValDisplay.textContent = currentZoom;
            }
            updateEstimate();
            checkSyncStatus();
        }
    });

    // Custom GPS marker icon
    const gpsIcon = L.divIcon({
        className: 'gps-marker',
        iconSize: [20, 20],
        iconAnchor: [10, 10]
    });

    // Update zoom level display on zoom
    const zoomSpan = document.getElementById('zoom-level');
    map.on('zoomend', function() {
        zoomSpan.textContent = map.getZoom();
    });

    let gpsMarker = null;
    let satGpsMarker = null;
    const satelliteLayer = L.layerGroup().addTo(satMap);
    const satMarkers = {};
    const satLines = {};
    
    const satelliteCache = {}; // { PRN: { data: satObj, lastSeen: timestamp } }
    const SAT_CACHE_TIMEOUT_MS = 10000; // Keep satellites alive for 10 seconds

    function calculateSubSatellitePoint(observerLat, observerLon, elevation, azimuth) {
        // Earth radius in km
        const R = 6371.0;
        // GPS satellite orbit radius in km (Earth radius + orbital altitude ~20200km)
        const r = 26571.0;
        
        // Convert to radians
        const lat1 = observerLat * Math.PI / 180;
        const lon1 = observerLon * Math.PI / 180;
        const el = elevation * Math.PI / 180;
        const az = azimuth * Math.PI / 180;
        
        // Calculate central angle gamma
        // cos(E + gamma) = (R/r) * cos(E)
        let cosE_plus_gamma = (R / r) * Math.cos(el);
        // clamp to [-1, 1] just in case
        cosE_plus_gamma = Math.max(-1, Math.min(1, cosE_plus_gamma));
        const gamma = Math.acos(cosE_plus_gamma) - el;
        
        // Destination calculation using spherical trigonometry
        const lat2 = Math.asin(Math.sin(lat1) * Math.cos(gamma) + Math.cos(lat1) * Math.sin(gamma) * Math.cos(az));
        const lon2 = lon1 + Math.atan2(Math.sin(az) * Math.sin(gamma) * Math.cos(lat1), Math.cos(gamma) - Math.sin(lat1) * Math.sin(lat2));
        
        // Convert back to degrees
        return {
            lat: lat2 * 180 / Math.PI,
            lon: lon2 * 180 / Math.PI
        };
    }

    // --- Manual Location Selection ---
    let manualMarker = null;
    const manualLocationContainer = document.getElementById('manual-location-container');
    const selectedCoordsSpan = document.getElementById('selected-coords');
    const setLocationBtn = document.getElementById('set-location-btn');
    
    let selectedLat = null;
    let selectedLon = null;

    map.on('click', function(e) {
        selectedLat = e.latlng.lat;
        selectedLon = e.latlng.lng;
        
        if (!manualMarker) {
            manualMarker = L.marker([selectedLat, selectedLon]).addTo(map);
        } else {
            manualMarker.setLatLng([selectedLat, selectedLon]);
        }
        
        if (selectedCoordsSpan) selectedCoordsSpan.textContent = `${selectedLat.toFixed(5)}, ${selectedLon.toFixed(5)}`;
        if (manualLocationContainer) {
            manualLocationContainer.style.display = 'block';
        }
    });

    if (setLocationBtn) {
        setLocationBtn.onclick = async function() {
            if (selectedLat === null || selectedLon === null) return;
            
            setLocationBtn.disabled = true;
            setLocationBtn.textContent = 'Saving...';
            
            try {
                const res = await fetch('/api/set_location', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lat: selectedLat, lon: selectedLon })
                });
                
                if (res.ok) {
                    if (manualMarker) {
                        map.removeLayer(manualMarker);
                        manualMarker = null;
                    }
                    if (manualLocationContainer) {
                        manualLocationContainer.style.display = 'none';
                    }
                } else {
                    alert('Failed to set location.');
                }
            } catch (err) {
                alert('Network error while setting location.');
            } finally {
                setLocationBtn.disabled = false;
                setLocationBtn.textContent = '現在地として登録';
            }
        };
    }

    // Update location info panel
    const latSpan = document.getElementById('lat');
    const lonSpan = document.getElementById('lon');
    const statusSpan = document.getElementById('gps-status');
    const timeUtcSpan = document.getElementById('time-utc');
    const timeSourceSpan = document.getElementById('time-source');
    const timeOffsetSpan = document.getElementById('time-offset');

    async function fetchLocation() {
        try {
            const response = await fetch('/api/location');
            if (response.ok) {
                const data = await response.json();
                
                let currentSats = data.satellites || [];
                const now = Date.now();
                
                // Update cache with current satellites
                currentSats.forEach(sat => {
                    if (sat.PRN) {
                        satelliteCache[sat.PRN] = {
                            data: sat,
                            lastSeen: now
                        };
                    }
                });
                
                // Build the final array of satellites to display
                let sats = [];
                for (const prn in satelliteCache) {
                    if (now - satelliteCache[prn].lastSeen > SAT_CACHE_TIMEOUT_MS) {
                        // Expired, remove from cache
                        delete satelliteCache[prn];
                    } else {
                        // Still valid, add to display list
                        sats.push(satelliteCache[prn].data);
                    }
                }
                
                // Sort by PRN to maintain consistent order
                sats.sort((a, b) => (a.PRN || 0) - (b.PRN || 0));
                
                // Update GPS Satellites List
                const satList = document.getElementById('satellite-list');
                if (satList && sats.length > 0) {
                    const placeholder = satList.querySelector('.sat-placeholder');
                    if (placeholder) placeholder.remove();

                    const existingNodes = {};
                    Array.from(satList.children).forEach(child => {
                        if (child.dataset.prn) existingNodes[child.dataset.prn] = child;
                    });

                    sats.forEach(sat => {
                        const prn = sat.PRN || '--';
                        const el = sat.el !== undefined ? sat.el : '--';
                        const az = sat.az !== undefined ? sat.az : '--';
                        const snr = sat.ss !== undefined ? sat.ss : '--';
                        const usedClass = sat.used ? 'used' : '';
                        
                        if (existingNodes[prn]) {
                            const node = existingNodes[prn];
                            if (node.className !== `sat-item ${usedClass}`) {
                                node.className = `sat-item ${usedClass}`;
                            }
                            node.querySelector('.sat-el-az').textContent = `El: ${el}°, Az: ${az}°`;
                            node.querySelector('.sat-snr').textContent = `${snr} dB`;
                            delete existingNodes[prn];
                        } else {
                            const node = document.createElement('div');
                            node.className = `sat-item ${usedClass}`;
                            node.dataset.prn = prn;
                            node.innerHTML = `
                                <div class="sat-id">${prn}</div>
                                <div class="sat-el-az">El: ${el}°, Az: ${az}°</div>
                                <div class="sat-snr">${snr} dB</div>
                            `;
                            satList.appendChild(node);
                        }
                    });
                    
                    Object.values(existingNodes).forEach(node => node.remove());
                } else if (satList) {
                    satList.innerHTML = '<div class="sat-placeholder">No satellites visible</div>';
                }

                if (data.lat !== null && data.lon !== null) {
                    const lat = parseFloat(data.lat);
                    const lon = parseFloat(data.lon);
                    
                    latSpan.textContent = lat.toFixed(5);
                    lonSpan.textContent = lon.toFixed(5);
                    statusSpan.textContent = "Active";
                    statusSpan.style.color = "#4CAF50";
                    
                    if (timeUtcSpan) {
                        timeUtcSpan.textContent = data.timestamp_utc || "---";
                    }
                    if (timeSourceSpan) {
                        timeSourceSpan.textContent = data.time_source || "---";
                    }
                    if (timeOffsetSpan) {
                        if (data.time_offset_sec !== null && data.time_offset_sec !== undefined) {
                            const ms = (data.time_offset_sec * 1000).toFixed(3);
                            timeOffsetSpan.textContent = `${ms} ms`;
                            if (Math.abs(data.time_offset_sec) > 0.1) {
                                timeOffsetSpan.style.color = "#F44336"; // Red if offset is > 100ms
                            } else {
                                timeOffsetSpan.style.color = "#4CAF50"; // Green if accurate
                            }
                        } else {
                            timeOffsetSpan.textContent = "N/A";
                            timeOffsetSpan.style.color = "";
                        }
                    }

                    if (!gpsMarker) {
                        gpsMarker = L.marker([lat, lon], {icon: gpsIcon}).addTo(map);
                        map.setView([lat, lon], map.getZoom()); // Use current zoom instead of forcing 12
                    } else {
                        gpsMarker.setLatLng([lat, lon]);
                    }

                    if (!satGpsMarker) {
                        satGpsMarker = L.marker([lat, lon], {icon: gpsIcon}).addTo(satMap);
                        satMap.setView([lat, lon], satMap.getZoom());
                    } else {
                        satGpsMarker.setLatLng([lat, lon]);
                    }
                    
                    // --- Draw Satellites on Map ---
                    if (sats.length > 0) {
                        const activePrns = new Set();
                        sats.forEach(sat => {
                            if (sat.el !== undefined && sat.az !== undefined && sat.el !== '--' && sat.az !== '--') {
                                const prn = sat.PRN;
                                activePrns.add(String(prn));
                                const satPos = calculateSubSatellitePoint(lat, lon, sat.el, sat.az);
                                
                                const color = sat.used ? '#4CAF50' : '#F44336';
                                const satIcon = L.divIcon({
                                    className: 'sat-marker',
                                    html: `<div style="background-color: ${color}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 5px rgba(0,0,0,0.5);"><span style="font-size: 8px; color: white; font-weight: bold;">${sat.PRN||''}</span></div>`,
                                    iconSize: [18, 18],
                                    iconAnchor: [9, 9]
                                });
                                
                                if (satMarkers[prn]) {
                                    satMarkers[prn].setLatLng([satPos.lat, satPos.lon]);
                                    satMarkers[prn].setIcon(satIcon);
                                    satMarkers[prn].setPopupContent(`<b>PRN:</b> ${sat.PRN}<br><b>Elev:</b> ${sat.el}°<br><b>Azim:</b> ${sat.az}°<br><b>SNR:</b> ${sat.ss} dB`);
                                    satLines[prn].setLatLngs([[lat, lon], [satPos.lat, satPos.lon]]);
                                    satLines[prn].setStyle({color: color});
                                } else {
                                    satMarkers[prn] = L.marker([satPos.lat, satPos.lon], {icon: satIcon})
                                        .bindPopup(`<b>PRN:</b> ${sat.PRN}<br><b>Elev:</b> ${sat.el}°<br><b>Azim:</b> ${sat.az}°<br><b>SNR:</b> ${sat.ss} dB`)
                                        .addTo(satelliteLayer);
                                    
                                    satLines[prn] = L.polyline([[lat, lon], [satPos.lat, satPos.lon]], {
                                        color: color,
                                        weight: 1,
                                        dashArray: '4, 4',
                                        opacity: 0.4
                                    }).addTo(satelliteLayer);
                                }
                            }
                        });
                        
                        Object.keys(satMarkers).forEach(prnStr => {
                            if (!activePrns.has(prnStr)) {
                                satelliteLayer.removeLayer(satMarkers[prnStr]);
                                satelliteLayer.removeLayer(satLines[prnStr]);
                                delete satMarkers[prnStr];
                                delete satLines[prnStr];
                            }
                        });
                    } else {
                        satelliteLayer.clearLayers();
                        Object.keys(satMarkers).forEach(k => delete satMarkers[k]);
                        Object.keys(satLines).forEach(k => delete satLines[k]);
                    }
                    // ------------------------------
                } else {
                    statusSpan.textContent = "Waiting for fix...";
                    statusSpan.style.color = "#FFC107";
                }
            } else {
                statusSpan.textContent = "Error";
                statusSpan.style.color = "#F44336";
            }
        } catch (e) {
            console.error("GPS fetch error:", e);
            statusSpan.textContent = "Offline";
            statusSpan.style.color = "#F44336";
        }
    }

    setInterval(fetchLocation, 2000);
    // Initial fetch
    fetchLocation();
    
    // --- Download Modal Logic ---
    const modal = document.getElementById('download-modal');
    const btn = document.getElementById('download-btn');
    const span = document.getElementById('close-modal');
    const zoomSelect = document.getElementById('max-zoom-select');
    const zoomValDisplay = document.getElementById('zoom-val-display');
    const estimateContainer = document.getElementById('estimate-container');
    const startBtn = document.getElementById('start-download-btn');
    const cancelBtn = document.getElementById('cancel-download-btn');
    
    let currentBounds = null;
    
    async function updateEstimate() {
        if (!currentBounds) return;
        
        estimateContainer.innerHTML = '<p style="margin: 0; font-size: 14px; color: #ddd;">Estimating...</p>';
        startBtn.disabled = true;
        
        const data = {
            min_lat: currentBounds.getSouth(),
            max_lat: currentBounds.getNorth(),
            min_lon: currentBounds.getWest(),
            max_lon: currentBounds.getEast(),
            target_level: zoomSelect.value
        };
        
        try {
            const res = await fetch('/api/estimate_download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (res.ok) {
                const est = await res.json();
                let timeStr = est.seconds > 60 ? `${(est.seconds/60).toFixed(1)} minutes` : `${est.seconds} seconds`;
                
                estimateContainer.innerHTML = `
                    <p style="margin: 0; font-size: 14px; color: #4CAF50;">
                        <strong>Estimate:</strong> ${est.tiles.toLocaleString()} tiles (~${est.megabytes} MB)<br>
                        <strong>Estimated Time:</strong> ${timeStr}
                    </p>
                `;
                if (est.tiles > 10000) {
                    estimateContainer.innerHTML += `
                        <p style="margin-top: 10px; font-size: 12px; color: #FFC107;">
                            ⚠️ <strong>タイル数が非常に多くなっています。</strong><br>
                            Zoom 15〜19は「道路の形や建物一つ一つ」が見えるほどの非常に詳細なデータです。そのため、市町村レベルの広い範囲をZoom 19まで指定すると、数十万枚のファイルが必要になります。<br><br>
                            <strong>減らすには:</strong><br>
                            1. スライダーで Max Zoom Level を下げる（例: 14や15にする）<br>
                            2. 矩形選択ツール（左の四角形アイコン）で、もっと狭い範囲（数ブロック程度）を囲み直す
                        </p>
                    `;
                }
                startBtn.disabled = false;
            } else {
                estimateContainer.innerHTML = '<p style="margin: 0; font-size: 14px; color: #F44336;">Estimate failed</p>';
            }
        } catch(e) {
            estimateContainer.innerHTML = '<p style="margin: 0; font-size: 14px; color: #F44336;">Network error</p>';
        }
    }
    
    if (btn) {
        btn.onclick = function() {
            modal.style.display = "block";
            document.getElementById('download-status').textContent = '';
            
            // If user hasn't drawn anything, use the full map bounds
            if (drawnItems.getLayers().length === 0) {
                currentBounds = map.getBounds();
            } else {
                currentBounds = drawnItems.getLayers()[0].getBounds();
            }
            
            const currentZoom = map.getZoom();
            if (zoomSelect) {
                zoomSelect.value = currentZoom;
                zoomValDisplay.textContent = currentZoom;
            }
            
            updateEstimate();
            checkSyncStatus(); // check if already syncing
        }
    }
    
    function closeModal() {
        modal.style.display = "none";
        drawnItems.clearLayers();
    }

    if (span) {
        span.onclick = closeModal;
    }
    
    window.onclick = function(event) {
        if (event.target == modal) {
            closeModal();
        }
    }
    
    if (zoomSelect) {
        zoomSelect.oninput = function() {
            zoomValDisplay.textContent = this.value;
        };
        zoomSelect.onchange = function() {
            updateEstimate();
        };
    }
    
    let wasSyncing = false;
    
    async function checkSyncStatus() {
        try {
            const res = await fetch('/api/sync/status');
            if (res.ok) {
                const state = await res.json();
                if (state.is_syncing) {
                    wasSyncing = true;
                    startBtn.style.display = 'none';
                    cancelBtn.style.display = 'inline-block';
                    document.getElementById('download-status').textContent = state.status;
                } else {
                    startBtn.style.display = 'inline-block';
                    cancelBtn.style.display = 'none';
                    document.getElementById('download-status').textContent = state.status;
                    
                    if (wasSyncing && state.status === 'Completed') {
                        wasSyncing = false;
                        const t = new Date().getTime();
                        tileLayer.setUrl(`/tiles/{z}/{x}/{y}.png?t=${t}`);
                    } else if (wasSyncing) {
                        wasSyncing = false;
                    }
                }
            }
        } catch(e) {}
    }
    
    if (cancelBtn) {
        cancelBtn.onclick = async function() {
            try {
                await fetch('/api/sync/cancel', { method: 'POST' });
                document.getElementById('download-status').textContent = 'Cancelling...';
                setTimeout(checkSyncStatus, 1000);
            } catch(e) {}
        };
    }
    
    if (startBtn) {
        startBtn.onclick = async function() {
            if (!currentBounds) return;
            const data = {
                min_lat: currentBounds.getSouth(),
                max_lat: currentBounds.getNorth(),
                min_lon: currentBounds.getWest(),
                max_lon: currentBounds.getEast(),
                target_level: zoomSelect.value
            };
            
            document.getElementById('download-status').textContent = 'Starting download...';
            startBtn.disabled = true;
            
            try {
                const res = await fetch('/api/download_bounds', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (res.ok) {
                    const result = await res.json();
                    document.getElementById('download-status').textContent = `Download started! Area: ${result.region}`;
                    startBtn.style.display = 'none';
                    cancelBtn.style.display = 'inline-block';
                    
                    // Poll status while modal is open
                    const pollInt = setInterval(async () => {
                        if (modal.style.display !== "block") {
                            clearInterval(pollInt);
                            return;
                        }
                        await checkSyncStatus();
                    }, 1000);
                    
                } else {
                    document.getElementById('download-status').textContent = 'Error starting download.';
                    startBtn.disabled = false;
                }
            } catch (err) {
                document.getElementById('download-status').textContent = 'Network error.';
                startBtn.disabled = false;
            }
        };
    }
});

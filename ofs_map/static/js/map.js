// map.js
document.addEventListener("DOMContentLoaded", () => {
    // Initialize map
    const map = L.map('map').setView([35.65, 139.75], 5); // Default to Japan roughly, zoom 5

    // Add local tile layer
    // errorTileUrl is handled by backend returning a gray image instead of 404,
    // but just in case, we can also provide a fallback or rely on backend.
    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

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
        edit: {
            featureGroup: drawnItems,
            remove: true
        }
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

    // Update location info panel
    const latSpan = document.getElementById('lat');
    const lonSpan = document.getElementById('lon');
    const statusSpan = document.getElementById('gps-status');

    async function fetchLocation() {
        try {
            const response = await fetch('/api/location');
            if (response.ok) {
                const data = await response.json();
                if (data.lat !== null && data.lon !== null) {
                    const lat = parseFloat(data.lat);
                    const lon = parseFloat(data.lon);
                    
                    latSpan.textContent = lat.toFixed(5);
                    lonSpan.textContent = lon.toFixed(5);
                    statusSpan.textContent = "Active";
                    statusSpan.style.color = "#4CAF50";

                    if (!gpsMarker) {
                        gpsMarker = L.marker([lat, lon], {icon: gpsIcon}).addTo(map);
                        map.setView([lat, lon], map.getZoom()); // Use current zoom instead of forcing 12
                    } else {
                        gpsMarker.setLatLng([lat, lon]);
                    }
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
            
            updateEstimate();
            checkSyncStatus(); // check if already syncing
        }
    }
    
    if (span) {
        span.onclick = function() {
            modal.style.display = "none";
        }
    }
    
    window.onclick = function(event) {
        if (event.target == modal) {
            modal.style.display = "none";
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
    
    async function checkSyncStatus() {
        try {
            const res = await fetch('/api/sync/status');
            if (res.ok) {
                const state = await res.json();
                if (state.is_syncing) {
                    startBtn.style.display = 'none';
                    cancelBtn.style.display = 'inline-block';
                    document.getElementById('download-status').textContent = state.status;
                } else {
                    startBtn.style.display = 'inline-block';
                    cancelBtn.style.display = 'none';
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

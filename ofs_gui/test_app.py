def test():
    options_html = ""
    stacked_files = ["test.fits"]
    selected_filename = "test.fits"
    if stacked_files:
        options_html += '<div class="list-title" style="padding: 6px 10px;">STACKED FILE</div>\n'
        for sf in stacked_files:
            sel = " selected" if sf == selected_filename else ""
            options_html += f'<div class="list-item{sel}" onclick="changeFile(\'{sf}\')"><div class="file-name" style="color: var(--accent-gold); font-weight: 600;">{sf}</div></div>\n'

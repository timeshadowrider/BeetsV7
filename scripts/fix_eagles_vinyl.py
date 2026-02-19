#!/usr/bin/env python3
import sqlite3, subprocess, os, re, shutil

conn = sqlite3.connect('/data/library.db')

ids = list(range(1925, 1940))
DEST_DIR = '/music/library/Eagles/(1977) Hotel California [Vinyl Rip]'
os.makedirs(DEST_DIR, exist_ok=True)

# Map vinyl side+position to sequential track number
# A=side 1, B=side 2, C=side 3, D=side 4
# Each side has up to 4 tracks
SIDE_OFFSET = {'A': 0, 'B': 4, 'C': 8, 'D': 12}

for rid in ids:
    row = conn.execute('SELECT path, title FROM items WHERE id=?', (rid,)).fetchone()
    if not row:
        continue
    path = row[0].decode() if isinstance(row[0], bytes) else row[0]
    path = path.strip("'\"")
    title = row[1].decode() if isinstance(row[1], bytes) else row[1]

    # Parse vinyl notation e.g. "B2 Hotel California"
    m = re.match(r'^([A-D])(\d)\s+(.*)', title)
    if m:
        side = m.group(1)
        pos = int(m.group(2))
        clean_title = m.group(3).strip()
        track_num = SIDE_OFFSET[side] + pos
    else:
        clean_title = title
        track_num = 0

    # Zero-padded track number for filename
    track_str = str(track_num).zfill(2)
    new_filename = os.path.join(DEST_DIR, '{} {}.flac'.format(track_str, clean_title))

    print(f'Track {track_str}: {clean_title}')
    print(f'  {path}')
    print(f'  -> {new_filename}')

    # Write corrected tags into new file
    subprocess.run([
        'ffmpeg', '-y', '-i', path,
        '-metadata', 'artist=Eagles',
        '-metadata', 'albumartist=Eagles',
        '-metadata', 'album=Hotel California',
        '-metadata', 'year=1977',
        '-metadata', 'date=1977',
        '-metadata', 'albumdisambig=Vinyl Rip',
        '-metadata', 'title={}'.format(clean_title),
        '-metadata', 'tracknumber={}'.format(track_num),
        '-metadata', 'tracktotal=15',
        '-c', 'copy', new_filename
    ], check=True, capture_output=True)

    # Update DB record
    conn.execute(
        '''UPDATE items SET
            artist=?, albumartist=?, album=?, year=?,
            title=?, track=?, tracktotal=?, path=?
           WHERE id=?''',
        ('Eagles', 'Eagles', 'Hotel California', 1977,
         clean_title, track_num, 15, new_filename, rid)
    )
    print(f'  Done')

conn.commit()
conn.close()

# Remove old untagged files and empty folder
old_dir = '/music/library/_/(0000)'
for f in os.listdir(old_dir):
    fp = os.path.join(old_dir, f)
    if os.path.isfile(fp):
        os.remove(fp)
        print(f'Removed old file: {fp}')

# Remove _ folder if now empty
root = '/music/library/_'
if os.path.exists(root):
    shutil.rmtree(root)
    print('Removed empty _/ folder')

print('\nDone -- verify with:')
print('  beet list albumartist:Eagles album:"Hotel California"')

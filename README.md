# Puck Report toolkit

Renders Puck Report NHL content from small JSON specs: recap videos, the "Last night in the NHL" score card, and single-screen news reels. Original synthesized music is added automatically.

## Setup (once per workspace)
```
python3 puck_toolkit.py setup     # downloads the 32 team logos (npm: react-nhl-logos) and converts them
```
Needs: python3 with numpy, pillow, scipy; ffmpeg; node/npm. Fonts: Inter Display if installed, else DejaVu.

## Commands
```
python3 puck_toolkit.py scores  spec.json   # 1080x1350 animated score card + still PNG
python3 puck_toolkit.py recap   spec.json   # 1080x1920 single-game recap
python3 puck_toolkit.py reel    spec.json   # 1080x1920 single-screen news reel (story or list)
```
Each run also writes `<out>_check.png`, a contact sheet of frames for a quick visual check.

## Spec formats
See `examples/`. Team codes: ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LA MIN MTL NJ NSH NYI NYR OTT PHI PIT SEA SJ STL TB TOR UTA VAN VGK WPG WSH.

- **scores**: `games: [[winner, w_score, loser, l_score, "OT"|"SO"|""], ...]`, `tag`, optional `title`/`sub`/`footer`.
- **recap**: `slides: [...]` with `type` one of:
  - `hook` {tag, headline, line, photo?}
  - `score` {tag, teams: [[city, name, score] winner first, [...]], line}
  - `periods` {rows: [[label, text, running score]], highlight?}
  - `photo_text` {tag, name, stat, sub, photo?, y0?}  (no photo -> big-text graphic)
  - `tiles` {tag, title, tiles: [[num, label] x3], note}
  - `list` {tag, title?, rows: [[name, label]], foot, photo?}
  - `numbers` {title, left, right, stats: [[label, a, b, fmt?, lower_is_better?]], note}
  - `outro` {}  (added automatically if missing)
  Photos: `"photo": {"path": "...", "focus_x": 0.5, "focus_y": 0.35, "box": [x0,y0,x1,y1], "top_dark": false}`.
- **reel**: `kind: "story"` {tag, headline, sub, items[], question?, source?, photo?}
  or `kind: "list"` {tag, title, sub, note, rows: [[team, name, subtitle, status]]}.

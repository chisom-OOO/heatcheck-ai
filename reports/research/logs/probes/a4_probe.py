"""Read-only probe of tests/test_time_integrity.py::test_preshot_future_perturbation_invariance.
Recomputes the same target selection and reports what the test actually exercised."""
import sqlite3, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, sys.argv[1] + "/src")
from heatcheck import features as F
DATA = Path(sys.argv[2])
con = sqlite3.connect(f"file:{DATA / 'public.sqlite'}?mode=ro", uri=True)
gids = [r[0] for r in con.execute("SELECT game_id FROM games ORDER BY tip_utc LIMIT 20")]
ev = pd.read_sql(f"SELECT * FROM events WHERE game_id IN ({','.join('?'*len(gids))})", con, params=gids); con.close()
gid = ev.game_id.iloc[0]
g = ev[ev.game_id == gid].sort_values("sequence"); shots = g[g.is_field_goal == 1]
s_seq = int(shots.sequence.iloc[len(shots)//2])
shooter = int(shots[shots.sequence == s_seq].person_id.iloc[0])
base = F.preshot_features(ev)
nxt = base[(base.game_id == gid) & (base.person_id == shooter) & (base.sequence > s_seq)]
print(f"game={gid} shots_in_game={len(shots)} target_seq={s_seq} shooter={shooter}")
print(f"invariance asserted for target shots: 1 of {len(base)} FGA rows built ({len(shots)} in the target game)")
print(f"later shots by same shooter (len(nxt)) = {len(nxt)} -> downstream branch {'EXECUTED' if len(nxt) else 'SKIPPED (vacuous)'}")
# how often would the downstream check be vacuous if the target were any shot in this game?
s = base[base.game_id == gid].sort_values("sequence")
last = s.groupby("person_id").sequence.transform("max") == s.sequence
print(f"if target were any shot in this game: {int(last.sum())}/{len(s)} targets have no later shot by same shooter (vacuous)")

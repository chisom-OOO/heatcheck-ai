# Idea-family runs (plan written before any run)

- `request_dev_example.json`: 12 ideas written by Research to exercise the machine on 2023-24 development
  games. This is **not** proposer output. Two are deliberate positive controls whose answer is known in
  advance: strong Elo favourites at home win more (`elo_gap home_fav_100+`), and 3-pointers go in less often
  (`shot_value 3`). If the machine did not flag those, it would be broken.
- `request_synthetic.json`: 13 SHOT ideas run on simulated leagues.
  - Primary league: family A, planted gamma = 0.30 log-odds, seed 20261108.
  - Control league: family A, gamma = 0, seed 20261109.
  - League parameters were chosen here, before running, and are revealed in each run's truth.json only
    after results.json.
- Commands:
  - `python -I scripts/idea_family.py dev <data_2023-24> evidence/idea-family/request_dev_example.json evidence/idea-family/dev_example`
  - `python -I scripts/idea_family.py synthetic evidence/idea-family/request_synthetic.json evidence/idea-family/synthetic_gamma030 --family A --gamma 0.30 --seed 20261108`
  - `python -I scripts/idea_family.py synthetic evidence/idea-family/request_synthetic.json evidence/idea-family/synthetic_gamma0 --family A --gamma 0 --seed 20261109`

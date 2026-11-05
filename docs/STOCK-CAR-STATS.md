# City Racing — stock vehicle stats

Read from pristine backup
(`2026-09-20_original-native\Data\Objects.pak`), not the live install.
Regenerate:

```
cd "D:\Projects Overflow\City Racing Work"
python carmod.py stock-list      # factory values
python carmod.py list            # whatever is installed right now
```

## Factory values

| car | model | HP | kg | force | accel | steer | drive | friction F/R | rolling F/R | susp stf/damp | refl | snd | force/kg |
|---|---|---:|---:|---:|---:|---:|:---:|---:|---:|---|---:|---:|---:|
| 01 | Galant S500 | 100 | 1000 | 2000 | 2 | 2 | RWD | 1.75 / 1.75 | 1.0 / 1.0 | 25 / 0.5 | 64 | 0 | 2.00 |
| 02 | Clio NSX | 100 | 800 | 1300 | 1.0 | 1.5 | RWD | 1.5 / 1.5 | 1.0 / 1.0 | 25 / 0.5 | 64 | 0 | 1.63 |
| 03 | Rover H1200 | 100 | 1200 | 1700 | 1.5 | 1.25 | RWD | 1.8 / 1.8 | 1.0 / 1.0 | 35 / 1.5 | 64 | 0 | 1.42 |
| 04 | Cosmo R200 | 100 | 1000 | 2300 | 2.0 | 1.75 | RWD | 2.0 / 2.0 | 1.0 / 1.0 | 25 / 0.5 | 64 | 0 | 2.30 |
| 05 | Thunder-1960 | 100 | 1200 | 1800 | 1.25 | 1.50 | RWD | 1.5 / 1.5 | 1.0 / 1.0 | 35 / 0.5 | 64 | 0 | 1.50 |
| 06 | Accord Z8 | 100 | 800 | 1300 | 1.0 | 1.25 | RWD | 1.25 / 1.25 | 1.0 / 1.0 | 25 / 0.5 | 64 | 0 | 1.63 |
| 07 | Alpha GRX8 | 100 | 1000 | 2200 | 2.25 | 2 | RWD | 2.0 / 2.0 | 1.0 / 1.0 | 25 / 0.5 | 64 | 0 | 2.20 |
| 08 | **Uber Atom-2000** | 100 | 1000 | **2500** | **2.5** | 2.0 | RWD | 2.0 / 2.0 | 1.0 / 1.0 | 35 / 1.5 | 64 | 0 | **2.50** |
| 01P | Galant S500 (Police) | 100 | 1000 | 2500 | 2.5 | 2.5 | RWD | 2.5 / 2.5 | 1.0 / 1.0 | 25 / 0.5 | 64 | 0 | 2.50 |
| 03P | Rover H1200 (Police) | 100 | 1200 | 2500 | 2.5 | 2.5 | RWD | 2.5 / 2.5 | 1.0 / 1.0 | 35 / 1.5 | 64 | 0 | 2.08 |

`drive` is `Front Tyre Driving` / `Rear Tyre Driving`; every stock car is `0/1` = RWD.

## Observations

- **Car 06 (Accord Z8) is strictly dominated by car 02 (Clio NSX).** Identical 800 kg /
  1300 force / 1.0 accel, but the Clio wins on steering (1.5 vs 1.25) and friction
  (1.5 vs 1.25) and loses on nothing. It is the worst car in the game by the numbers.
- **Car 08 (Uber Atom-2000) is the best.** It matches the police tune on force (2500) and
  acceleration (2.5), giving up only steering and grip, and it gets the good suspension.
- **The police tune — 2500 / 2.5 / 2.5 / 2.5 — is the developers' own ceiling.** No stock
  car exceeds it on any axis, so it is a *known-stable* upper bound for tuning. Values above
  it are extrapolation, where rollovers and physics breakdown start.
- **Suspension comes in two flavours**, 25 / 0.5 (soft) and 35 / 1.5 (stiff) — except
  **Thunder-1960, which is 35 / 0.5**: stiff but underdamped, so it resists compression then
  oscillates. Looks like an oversight rather than a design choice.
- Every car: 100 health, rolling resistance 1.0/1.0, reflection 64, engine sound ID 0.
- **Never raise `Base Health`.** Repair cost is priced per hit point lost and damage scales
  with max health, so raising 100 to 9999 multiplies the repair bill ~100x while buying
  little real durability. Confirmed in play, 2026-09-20.
- Prices and progression are **not** in the archives (all 284 configs searched) — they live
  in `game.exe`.

## Ranking by power-to-weight

```
08 Uber Atom-2000   2.50  ####################
04 Cosmo R200       2.30  ##################
07 Alpha GRX8       2.20  #################
01 Galant S500      2.00  ################
02 Clio NSX         1.63  #############
06 Accord Z8        1.63  #############   (but worse steering + grip)
05 Thunder-1960     1.50  ############
03 Rover H1200      1.42  ###########
```

Power-to-weight is not the whole story — grip and steering decide lap time in a game where
sliding is the main way you lose speed. Car 03 is the slowest on paper but has the best stock
friction of any non-police car (1.8) plus stiff suspension.

# FlickerGuard: design spec and project outline

**Team 11** · CUES × Edge Impulse × Cambridge MedTech Foundation Hackathon · 21–22 Nov 2026
**Status:** v0.2 draft (Modulino Light as the only light sensor), a living document. Code and dev tooling are on the
[`otk/dev`](https://github.com/ua246/Team11_EdgeImpulseHackathon/tree/otk/dev) branch.

> A wearable for people with photosensitive epilepsy. It **warns** the wearer about
> seizure-provoking flashing light, and if a convulsive seizure follows anyway, it **detects it and
> alerts a carer**. All of this runs offline on an Arduino UNO Q with Edge Impulse models.

---

## 1. Summary

| | |
|---|---|
| **Problem** | Flashing light can trigger seizures in photosensitive epilepsy. People have to notice the trigger themselves, and the trigger is what impairs them. Seizures often happen with nobody around. |
| **Users** | People with photosensitive epilepsy (wearer), parents and carers (alarm), epilepsy nurses and neurologists (exposure and event log) |
| **Solution** | Two loops on one device. **Prevent:** detect hazardous flicker and alert the wearer within about 1 s. **Detect:** recognise convulsive shaking and alarm a carer. Watch more closely in the minutes after a hazardous exposure. |
| **Edge AI** | Two Edge Impulse models on the UNO Q: a light-risk classifier and a seizure-like-motion classifier, plus rule-based combining logic |
| **Hardware** | UNO Q, Modulino Light, Modulino Movement, Modulino Vibro / Buzzer / Buttons, power bank |
| **Demo** | Shielded flicker → wearer alert. Normal light changes → nothing. Acted shaking → carer alarm, which the wearer can cancel. |

---

## 2. Clinical need

**Background:**
- About **1 in 100** people has epilepsy, and about **3%** of them have photosensitive epilepsy (PSE).
  [1]
- Flashing at **3–30 Hz** is the most common trigger, and **16–25 Hz** is the most likely range.
  It varies by person: some react up to about 60 Hz, and sensitivity below 3 Hz is uncommon. [1][2]
- The advice on sudden exposure is to **cover one eye completely and turn away, without closing the
  eyes**. That only helps if the person notices in time. [1][3]
- **Rules cover screens, not the real world.** Broadcast and web content have flash limits
  (UK broadcast guidance; WCAG 2.3.1 [4]), but strobes, emergency-vehicle lights, sunlight through
  trees and games in a dark room have none.
- **Seizure alarms are recommended.** The ILAE / IFCN 2021 clinical practice guideline suggests
  clinically validated wearable devices for detecting **tonic-clonic seizures**, especially in
  unsupervised patients, so that someone can be alerted. Evidence for other seizure types was
  weaker. [5]

**Setting:**
- *Where:* everyday life: clubs and concerts, roads, gaming, cinema.
- *When:* the first seconds of exposure, which is the window for protective action, and the
  minutes after it, when a seizure may follow.
- *Over time:* weeks of exposure and event logs, for clinic review.

**Why on the device (edge):**
- an alert only helps within about a second;
- it has to work without signal (clubs, cars);
- no camera or cloud is needed, so it's private;
- streaming nothing saves battery.

**Scope and non-goals:**
- Motion-based detection covers **convulsive (tonic-clonic)** seizures only. Absences and small
  myoclonic jerks need EEG and are out of scope.
- This is a hackathon prototype trained on acted and simulated data. It is not a validated
  medical device.

---

## 3. System overview

```
 CAP (front)                      ARM SLEEVE (or chest holder)                    OUTPUTS
 ┌─────────────────────┐ Qwiic   ┌──────────────────────────────────────────┐
 │ Modulino Light      ├────────▶│ UNO Q · MCU (STM32U585)                  │──▶ Vibro: wearer alert
 │ (flicker + colour,  │         │  fixed-rate sampling, output drivers     │──▶ Buzzer: carer alarm
 │  ≤40/s, in a tube)  │         │        │ Bridge (UART, 115200 baud)      │──▶ LED matrix: static icons
 └─────────────────────┘         │        ▼                                 │◀── Buttons: cancel / ack
 WRIST / ARM                     │ UNO Q · Linux (QRB2210)                  │
 ┌─────────────────────┐ Qwiic   │  Edge Impulse models, alert logic,       │
 │ Modulino Movement   ├────────▶│  exposure + event log                    │
 └─────────────────────┘         │        power bank (USB-C)                │
                                 └──────────────────────────────────────────┘
```

---

## 4. Functional requirements

| ID | Requirement | Priority | Verified by |
|---|---|---|---|
| F1 | Detect flicker at 3–30 Hz and classify it: steady / harmless change / hazardous / hazardous red. The frequency is read correctly up to about 15 Hz; faster flicker is still detected, at a folded frequency (DI-01) | **MVP** | T1, T2 |
| F2 | Vibrate within **≤ 1 s** of hazardous flicker starting | **MVP** | T4 |
| F3 | No alert for steady light, light switching, head turns, slow (< 3 Hz) indicators, or mains ripple | **MVP** | T2 |
| F4 | Detect sustained rhythmic convulsive-like shaking, and tell it apart from vigorous normal activity | Should | T3 |
| F6 | After a hazardous exposure, raise seizure-detection sensitivity for a 5-minute watch window | Should | T5 |
| F7 | Carer alarm (buzzer + LED matrix + log), preceded by a 15 s countdown the wearer can cancel | Should | T5 |
| F8 | Log exposures and events: time, duration, dominant frequency, red or not, acknowledged or cancelled | Should | T5 |
| F9 | A per-patient sensitive frequency range (from their EEG photic-stimulation result) raises the alert level | Stretch | – |
| F10 | A servo shutter over one eye on a high-severity exposure | Stretch | – |

## 5. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| N1 | Runs fully offline; all models run on the UNO Q | Hackathon rule |
| N2 | Latency, flicker onset → vibration | ≤ 1 s |
| N3 | Latency, sustained shaking → alarm | Countdown starts after ≤ 10 s of shaking (≤ 5 s in the watch window) |
| N4 | False hazard alerts in normal indoor wear | ≤ 1 per hour (measured in the dinner-break wear test) |
| N5 | False seizure alarms in normal wear | 0 in a 30-minute wear test |
| N6 | Wearable: about 1 h on one power bank, cables strain-relieved, light parts on the cap | Measured |
| N7 | Safety: nothing on the device flashes; analog inputs ≤ 3.3 V; demo flicker always shielded | Rule |
| N8 | Privacy: no images captured or stored; data stays on the device | Rule |

---

## 6. Hardware

| Part | Placement | Connection | Rate | Role |
|---|---|---|---|---|
| Arduino UNO Q | Arm sleeve or chest holder | Power bank (USB-C) | – | Sampling (MCU), models and logic (Linux) |
| Modulino Light (LTR-381RGB, I2C 0x53) | Cap brim, facing forward, in a short black tube | Qwiic (`Wire1`) | ≤ 40/s (25 ms each) | **The flicker sensor:** brightness swing, flicker frequency (correct up to about 15 Hz, folded above 20 Hz), colour (red share) |
| Modulino Movement (LSM6DSOX) | Wrist / forearm (sleeve) | Qwiic | 50/s | Seizure-like motion |
| Modulino Vibro | Sternum (chest strap) or temple | Qwiic | – | Silent wearer alert |
| Modulino Buzzer | Board / sleeve | Qwiic | – | Carer alarm |
| Modulino Buttons | Sleeve | Qwiic | – | Cancel / acknowledge |
| UNO Q LED matrix | Board | – | – | **Static** status icons only |
| *Optional:* servo + flap | Cap | PWM pin + 5 V from the power bank | – | F10 |

**Electrical rules (DI-05):**
- 3.3 V logic. A0/A1 are not 5 V tolerant, and no pin may exceed 3.3 V in analog mode.
- Servos and motors take 5 V from the power bank and share ground.
- Run an I2C scan once everything is on the Qwiic chain; Modulino addresses differ by type.

**Test rig:** `hardware/light-test` (KiCad, on `otk/dev`): a test LED on D3 flashing into the Modulino Light, used by
`apps/light-test` (T1).

---

## 7. Software architecture

| Layer | Runs on | Does |
|---|---|---|
| Sketch | STM32 (Zephyr core) | Fixed-rate sampling; reads the light sensor's registers directly (the library call blocks for 50–150 ms, DI-02); batches CSV text to Linux every 100 ms; drives Vibro / Buzzer / matrix |
| Python app | Linux (App Lab app) | Receives the streams, keeps sliding windows, runs both Edge Impulse models, alert state machine, logging |
| Tooling | Laptop | `tools/unoq` (push / restart / logs / record / pull / compile) and VSCodium tasks; see `docs/UNOQ_DEV.md` on `otk/dev` |

**Bridge budget (DI-04).** The link is about 11 KB/s in total. The current streams use about
2 KB/s (IMU 50/s, light 40/s), so there is plenty of headroom.

---

## 8. Edge AI (Edge Impulse)

| | Model A: light risk | Model B: seizure-like motion |
|---|---|---|
| **Inputs** | Modulino Light R/G/B (≤ 40/s) | IMU accel + gyro (50/s) |
| **Window / stride** | 2 s / 250 ms | 4 s / 1 s |
| **Processing** | Spectral analysis (FFT); brightness swing | Spectral analysis |
| **Classes** | `steady`, `benign_change`, `flicker_hazard`, `flicker_red` | `rest`, `normal_activity` (walk, wave, clap, brush teeth, type, stir), `shaking_sim` |
| **Learning block** | Small dense NN (+ optional anomaly detection) | Small dense NN (+ optional anomaly detection) |
| **Post-processing** | Alert if ≥ 0.8 in 2 of the last 3 windows **and** brightness swing ≥ threshold (DI-18) | Countdown if ≥ 0.8 sustained for 10 s (5 s in the watch window) |
| **Baseline to beat** | Rule-based flash counter (> 3 swings/s of ≥ 10%) | Rule on acceleration energy in the shaking band |
| **Training data** | Flicker page sweep (1–30 Hz, white/red/blue; above 20 Hz it arrives folded, so label by the true rate), LED test rig 1–35 Hz, fan/chopper + lamp, phone strobe, harmless light changes, real-world dinner-break wear | Acted shaking at several rates and intensities; hard negatives: vigorous normal activity; at least 2 people, one held out for testing |
| **Report** | Per-class precision/recall, false alerts per hour, latency, on-device inference time | Per-class precision/recall, false alarms in 30-minute wear, time to alarm |

**Data capture:** `tools/unoq record <label> <seconds>` writes per-stream CSVs (timestamp in ms)
for the Edge Impulse CSV Wizard. The label comes from the file-name prefix.

---

## 9. Alert logic

```
            hazardous flicker (Model A)
 MONITOR ─────────────────────────────▶ EXPOSURE ALERT ──(flicker gone)──▶ WATCH (5 min)
    ▲       vibrate, log, [shutter]                                         │ heightened
    │                                                                       │ sensitivity
    │      sustained shaking (Model B)                                      ▼
    ├──────────────────────────────────────────────────────────▶ SEIZURE SUSPECTED
    │                                                            15 s countdown, vibro pulses
    │◀──── wearer presses CANCEL (logged as false alarm) ─────────────────┤
    │                                                                     ▼ no cancel
    └──────────────────────────── acknowledged ◀───────────────────── CARER ALARM
                                                                  buzzer, LED icon, log
```

---

## 10. Validation and test plan

| Test | What | Pass |
|---|---|---|
| T1 | `apps/light-test`: test LED at 1–35 Hz and short flashes into the Modulino Light; checks the 40 readings/s + 25 ms averaging model | **PASS** on "10 Hz flicker"; measured correct-frequency band (expected about 1–15 Hz) goes into the pitch |
| T2 | Model A on held-out data; flicker page at 5/10/15 Hz, plus 25 Hz (folded, must still alert); harmless set; distance 0.5–3 m in dim and lit rooms | F1, F3, N4 |
| T3 | Model B on a held-out person; hard negatives; 30-minute normal wear | F4, N5 |
| T4 | Latency: flicker onset → vibration (log timestamps or slow-motion phone video) | N2 |
| T5 | End-to-end rehearsal of the demo script, 5 times | All MVP + Should, under 3:00 |
| T6 | Runtime on the power bank | N6 |

---

## 11. Demo (3 minutes)

1. **0:00–0:30 · Problem:** the PSE numbers; the cover-one-eye advice needs warning; seizures
   happen alone.
2. **0:30–0:50 · Device:** cap with sensors, arm sleeve with the UNO Q. Everything offline.
3. **0:50–1:40 · Prevent:**
   - room light switching and head turns → no alert;
   - 2 Hz indicator-style flashing → no alert;
   - 10 Hz flicker *inside a tube* → vibration within about 1 s;
   - red flicker → stronger pattern.
4. **1:40–2:20 · Detect:** waving and clapping → nothing. Acted rhythmic shaking → countdown →
   cancel once, then let it run to the carer alarm.
5. **2:20–2:45 · Evidence:** results tables against the rule baselines, false alerts per hour,
   latency, inference time on the UNO Q.
6. **2:45–3:00 · Next steps:** personal range from EEG, clinical evaluation, glasses-clip version.

**Demo safety (DI-12):** never strobe the open room. Warn the audience first, and record a backup
video.

## 12. Judging criteria

| Criterion | Pts | How we score |
|---|---|---|
| Creativity | 10 | Prevent + detect in one device; the watch window links exposure to seizure detection; colour-aware flicker detection |
| Edge AI integration | 15 | Two Edge Impulse models on the UNO Q, offline; both beat rule baselines; latency-critical |
| Clinical relevance | 15 | Epilepsy Society guidance; frequency bands from the literature; ILAE/IFCN 2021 guideline on seizure-detection wearables; clinic log |
| Hardware implementation | 10 | Purposeful sensor placement, silent alert, cancel button, nothing flashes, sensor characterised on a test rig (KiCad) |
| Presentation + demo | 15 | Clear yes/no moments for both loops; shielded flicker; backup video |

---

## 13. Plan and roles

| When | Goal |
|---|---|
| Sat → 18:00 | Rig built, **T1** run; data collection for Model A |
| 18:00–18:30 | Dinner-break wear test: real-world light data and false-alert baseline |
| 18:30–21:00 | Model A trained and deployed; wearer alert working. Shaking data collected |
| Sun 09:00–10:30 | Model B + countdown / cancel / alarm |
| 10:30–11:15 | Results table; rehearse 5 times; backup video |
| 11:15–**12:00** | **Devpost submission** (deadline 12:00) |
| 13:00 | Judges panel |

**Roles (TBD):** hardware and firmware · ML and data · clinical case and pitch

## 14. Top risks

Full log: `docs/DESIGN_ISSUES.md` on
[`otk/dev`](https://github.com/ua246/Team11_EdgeImpulseHackathon/blob/otk/dev/docs/DESIGN_ISSUES.md).

| Risk | Mitigation |
|---|---|
| Modulino Light tops out at 40/s: frequencies above about 18 Hz read wrong, and part of the 16–25 Hz peak band folds (DI-01) | Accepted (DI-22). T1 measures the real band; Model A is trained on the folded signal so it still alerts; the pitch states the limit |
| No real seizure data (DI-09) | Hard negatives, cancel button, honest framing, false-alarm measurement |
| Two models in about 10 h | Model A is MVP; Model B is "Should"; fall back to light-only FlickerGuard (§15) |
| Demo hardware failure | Strain relief, spare cables, backup video |

---

## 15. Fallback and rejected options

| Fallback | What | When to switch |
|---|---|---|
| **FlickerGuard light-only** | Prevent loop only: Model A + vibration + log (+ servo eye shutter, F10). Same hardware | Model B isn't working by Sunday 10:00 |

**Rejected:**
- Two interleaved Modulino Lights for 80 readings/s: clock drift and too much effort (DI-01).
- Other light sensors: evaluated on the board and dropped (DI-22).

## 16. Open decisions

- [ ] Alert threshold (brightness swing): set from the T2 distance data.
- [ ] IMU placement: wrist or upper arm? Check cable length and signal on acted shaking.
- [ ] Vibro placement: temple or sternum? Pick whichever is more noticeable.
- [ ] Watch-window length and thresholds: tune from data.
- [ ] Devpost track name and final project name.

## 17. Submission draft (Devpost)

> **FlickerGuard** is a wearable for people with photosensitive epilepsy, running two Edge Impulse
> models fully offline on an Arduino UNO Q. A cap-mounted light sensor recognises seizure-provoking
> flicker in the real world and buzzes the wearer within about a second, prompting the advice to
> cover one eye. A motion sensor on the arm then watches for a convulsive seizure.
> It watches more closely after a risky exposure, and alarms a carer unless the wearer cancels.
> Every exposure and event is logged for the neurologist.

## References

1. Epilepsy Society: Photosensitive epilepsy. https://epilepsysociety.org.uk/node/3176
2. Epilepsy Society: Photosensitive epilepsy leaflet (July 2023). https://epilepsysociety.org.uk/sites/default/files/2023-07/PhotosensitiveepilepsyJuly2023.pdf
3. Epilepsy Society: Minimising risk from flashing lights. https://epilepsysociety.org.uk/node/3618
4. W3C: Understanding WCAG 2.1 SC 2.3.1, Three Flashes or Below Threshold. https://www.w3.org/WAI/WCAG21/Understanding/three-flashes-or-below-threshold.html
5. Beniczky S. et al. Automated seizure detection using wearable devices: a clinical practice guideline of the ILAE and IFCN. *Epilepsia / Clinical Neurophysiology*, 2021. https://pubmed.ncbi.nlm.nih.gov/33678577/
6. Arduino: UNO Q, Modulino, App Lab and Bridge documentation. https://docs.arduino.cc/hardware/uno-q/
7. Edge Impulse: Arduino UNO Q support. https://docs.edgeimpulse.com/hardware/boards/arduino-uno-q

# Archive

Apps that aren't part of FlickerGuard v0.1, kept for reference. `tools/unoq` only runs apps in
`apps/`; move one back there to use it again.

| App | Why it's here |
|---|---|
| `sensor-stream` | The first streaming/recording app (Modulino Light + Movement, `tools/unoq record`). Replaced by `apps/flicker-guard`, which records light, movement and events itself. It uses the Arduino_Modulino library, which stops sketches starting on our board with package 1.1.0 (DI-24); port it to register drivers before reuse |
| `max30102-heart-rate` | A teammate's standalone MAX30102 heart-rate app. Heart-rate sensing was dropped from the design (DI-22); kept unchanged |

Earlier evaluations (camera, heart-beat sensor as a flicker detector) are in git history at commit
`65e6c7f` (DI-22).

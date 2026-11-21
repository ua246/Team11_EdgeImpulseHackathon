# Team11_EdgeImpulseHackathon

## Getting started (UNO Q + VSCodium)

1. Install adb (`sudo pacman -S android-tools` / `sudo apt install adb`), plug in the UNO Q, run `tools/unoq doctor`.
2. Open this folder in VSCodium and accept the recommended extensions.
3. Press **Ctrl+Shift+B**: pushes `apps/sensor-stream` to the board, restarts it, and shows the Python and microcontroller output side by side.

`apps/sensor-stream` streams the Modulino Light and Modulino Movement, prints live rates and values, and records labelled CSVs for Edge Impulse (`tools/unoq record <label> <seconds>`).

`apps/light-test` measures how well the Modulino Light reads flicker, using a test LED (rig: `hardware/light-test`): `UNOQ_APP=light-test tools/unoq dev`.

Full guide: [docs/UNOQ_DEV.md](docs/UNOQ_DEV.md)

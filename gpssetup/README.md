# OrionFieldStack

**OrionFieldStack** is an open-source project designed for astronomical observation and field computing automation, developed by **voyager3.stars**.

Official Web: [voyager3.stars](https://voyager3.stars.ne.jp)

---

## Component: setup-timesync.sh

This script provides an automated environment setup for high-precision time synchronization using GPS and Chrony, specifically optimized for Raspberry Pi OS (Bookworm).

### Features
* **Automated UART Configuration**: Enables hardware serial and disables serial console conflicts.
* **Optimized GPSD Setup**: Configures the GPS daemon for stable satellite data reception.
* **Chrony Integration**: Connects GPS (SHM 2) to Chrony for microsecond-level time precision, essential for accurate astronomical logging.
* **Error Resilience**: Includes fixes for Windows-edited line endings and service masking.

### Installation

```bash
git clone [https://github.com/voyager3stars/OrionFieldStack.git](https://github.com/voyager3stars/OrionFieldStack.git)
cd OrionFieldStack
chmod +x gpssetup.sh
sudo ./gpssetup.sh

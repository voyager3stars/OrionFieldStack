import sys
import time
import os
import signal
import subprocess
import lgpio

PID_FILE = "/tmp/atm0130_bl.pid"
LOG_FILE = "/tmp/atm0130_bl.log"

def stop_daemon():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            os.remove(PID_FILE)
        except Exception:
            pass

def main():
    duty = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
    duty = max(0.0, min(100.0, duty))

    stop_daemon()

    if duty >= 100.0:
        subprocess.run(["pinctrl", "set", "23", "op", "dh"], check=False)
        print(f"Backlight set to 100% (Pin 16 locked HIGH)")
        return
    elif duty <= 0.0:
        subprocess.run(["pinctrl", "set", "23", "op", "dl"], check=False)
        print(f"Backlight set to 0% (Pin 16 locked LOW)")
        return

    pid = os.fork()
    if pid > 0:
        with open(PID_FILE, "w") as f:
            f.write(str(pid))
        print(f"Backlight PWM set to {duty}% (Daemon PID {pid})")
        return

    os.setsid()
    with open(LOG_FILE, "w") as log:
        try:
            log.write(f"Starting lgpio PWM duty={duty}...\n")
            log.flush()
            h = lgpio.gpiochip_open(15)
            # CRITICAL: Must claim as output before tx_pwm!
            lgpio.gpio_claim_output(h, 23, 0)
            lgpio.tx_pwm(h, 23, 1000, duty)
            log.write("tx_pwm called successfully! Running loop...\n")
            log.flush()
            while True:
                time.sleep(10)
        except Exception as e:
            log.write(f"Exception: {e}\n")
            log.flush()

if __name__ == "__main__":
    main()

# Guide: waking the home PC (Wake-on-LAN)

Part of [home-pc.md](home-pc.md). Goal: the PC is suspended, and you wake it from the library or the office.

## How it works

While the PC is suspended, the operating system and with it Tailscale are frozen. Only the Ethernet chip
(`enp6s0`) is still powered, at a trickle. It watches the cable for a **magic packet**: a frame that contains the
PC's MAC address 16 times in a row. When it sees one, it wakes the mainboard. Linux and `tailscale0` play no part.

The magic packet is usually sent as a broadcast inside the home network. Routers do not forward broadcasts from
the internet, and Tailscale only carries IP traffic between running devices. So the packet has to be sent by
something **inside** the home network that is awake:

```
laptop ──internet/Tailscale──▶ sender at home (router or always-on device) ──broadcast──▶ enp6s0 ──▶ PC wakes
```

Four things must work, and the tests below check them one at a time:

1. the PC side: BIOS and network card stay ready in suspend,
2. the packet reaches the PC,
3. suspend and wake-up themselves work,
4. a sender at home can be triggered while you are away.

## 1. PC side

### BIOS / UEFI

Enter the setup at boot (usually `Del` or `F2`). The names differ by board maker; look for:

- **Wake-on-LAN:** "Wake on LAN", "Power On By PCI-E", "Resume by PCI-E Device", "PCIE Devices Power On". Enable.
- **ErP / EuP / Deep Sleep:** an energy-saving mode that cuts standby power to the network chip. Disable.
- Optional, **Restore on AC Power Loss:** "Power On" makes the PC start by itself after a power cut. Otherwise it
  stays off, and depending on the board WoL then does not work until it has been switched on once.

### Network card, in Linux

```bash
sudo pacman -S ethtool
ip link show enp6s0                 # MAC address after "link/ether", e.g. 3c:7c:3f:aa:bb:cc: write it down
sudo ethtool enp6s0 | grep -i wake  # "Supports Wake-on: pumbg" must contain g (magic packet)
nmcli c show                        # connection name of enp6s0, e.g. "Wired connection 1"
sudo nmcli c modify "Wired connection 1" 802-3-ethernet.wake-on-lan magic
sudo nmcli c up "Wired connection 1"
sudo ethtool enp6s0 | grep -i wake  # now "Wake-on: g"
```

NetworkManager sets this every time the connection comes up, so it survives reboots. Check `Wake-on: g` once more
after a reboot.

### Suspend type

```bash
cat /sys/power/mem_sleep            # the value in brackets is used
```

`[deep]` is classic suspend-to-RAM (S3), which a 2016 desktop should use. With `[s2idle]`, WoL often works too,
but if it does not, that is the first suspect.

## 2. Test: does the packet reach the PC? (PC awake, laptop at home)

This separates the sender from the PC side. The laptop needs no new program: `uv` can run the small Python tool
`wakeonlan` once without installing it.

1. Laptop at home on the home network (Wi-Fi is fine: the router passes the broadcast to the wired ports).
   Tailscale may stay on, but no exit node.
2. Find the broadcast address of the home network. On the laptop, `ipconfig`: with IPv4 address
   `192.168.1.57` and subnet mask `255.255.255.0`, the broadcast address is `192.168.1.255` (last number 255).
3. On the PC (awake), watch for the packet:

   ```bash
   sudo pacman -S tcpdump
   sudo tcpdump -i enp6s0 -n 'udp port 9 or ether proto 0x0842'
   ```

4. On the laptop (PowerShell), send it:

   ```powershell
   uvx wakeonlan -o 192.168.1.255 3c:7c:3f:aa:bb:cc
   ```

   `-o` sends to the home network's broadcast address (check `uvx wakeonlan --help`; options differ between versions). Without it, Windows may send the broadcast out of the wrong
   adapter (e.g. the Tailscale one).

`tcpdump` must print a line like `192.168.1.57.xxxxx > 192.168.1.255.9: UDP, length 102`. 102 bytes is a
magic packet. No line: the packet does not arrive, so check the broadcast address, exit node, guest Wi-Fi or
"client isolation" in the router. The PC side does not matter yet.

## 3. Test: wake from suspend (at home)

1. On the PC: `systemctl suspend`. Wait about 30 s until the fans stop and the power LED changes.
2. Look at the Ethernet port, at the PC and at the router or switch: the **link LED must stay lit**. Dark means the
   chip has no power in suspend: check ErP/Deep Sleep and the WoL option in the BIOS.
3. From the laptop: `uvx wakeonlan -o 192.168.1.255 <MAC>`. The PC should wake within a few seconds.
4. After 10–30 s, `ssh home` must work again: `tailscaled` has to reconnect first.
5. Also check that the PC wakes cleanly with the screen on. **Test resume at the PC first** (suspend, wake with a
   key): if that fails, the problem is resume, not WoL. A black screen and no `ssh` after a wake-up usually means
   the system hung while resuming, typically in the NVIDIA driver. See "NVIDIA resume" below.

### NVIDIA resume

`ping <LAN IP>` from the laptop tells a hang (no reply: hold the power button) from a Tailscale that has not
reconnected yet (reply). After a restart, `journalctl -b -1 | grep -iE 'nvidia|PM: |suspend|resume' | tail -50`
shows the end of the failed resume. The driver can only restore the card's memory if it saved it before suspend:

```bash
systemctl is-enabled nvidia-suspend nvidia-resume nvidia-hibernate   # all must be enabled
grep -i PreserveVideoMemory /proc/driver/nvidia/params               # must be 1
```

If the services are not enabled: `sudo systemctl enable nvidia-suspend nvidia-resume nvidia-hibernate`. If the
parameter is 0: write `options nvidia NVreg_PreserveVideoMemoryAllocations=1 NVreg_TemporaryFilePath=/var/tmp` to
`/etc/modprobe.d/nvidia-power.conf`, run `sudo mkinitcpio -P` (or the initramfs tool of the install), reboot.

Observed on this PC (2026-11-15): one suspend hung on the way **in**, not on resume. Signs in the log:
`systemd-suspend.service: Failed with result 'timeout'`, `nvidia-sleep.sh` blocked in `rm_power_management`, and
`nvidia-modeset` blocked in `__nv_drm_connector_detect_internal` (a deadlock in the driver). Fans and LEDs then stay
on, the screen stays black, SSH does not answer. Later suspends worked. Count how often it happens:
`journalctl -u systemd-suspend --since -14d | grep -c "Failed with result"` against
`journalctl --since -14d | grep -c "PM: suspend entry"`.

If suspend keeps failing: power off instead of suspending, and wake from off. Every wake-up is then a fresh boot
(30–60 s longer), it draws even less power than suspend, and it needs WoL from off (ErP/Deep Sleep disabled). In
`scripts/home/idle-suspend.sh`, replace `systemctl suspend` with `systemctl poweroff`. Check first that the sender
can wake the PC from off: in the test on 2026-11-15, `uvx wakeonlan` from the laptop did, the FRITZ!Box button
did not.

Optional: the same test from powered off (`sudo poweroff`). Not needed for daily use, but it shows whether the PC
can still be woken after a power cut.

## 4. A sender you can trigger from outside

### Can the router do it?

Find out which router you have: the model is on its sticker, or open the "Default Gateway" address from
`ipconfig` in a browser (e.g. `http://192.168.1.1`). Then search its web interface and manual for "Wake on LAN",
"WOL" or "start computer". It is usually in the list of network devices, on the page of a single device. The
FRITZ!Box has a button "Gerät starten" in the details of a network device (tested 2026-11-15: wakes the PC from
suspend, not from powered off; only short suspends tested so far). It sends a raw Ethernet broadcast (EtherType
`0x0842`, not UDP), so it does not depend on the router still remembering the PC's address.

Test in three steps:

1. **The function exists:** a button or menu as above, with the PC's MAC address.
2. **It works at home:** suspend the PC (test 3), then press the router's button. The PC wakes: the router can send.
3. **You can trigger it from outside.** The router's web interface is normally reachable only from the home
   network, so you also need one of:
   - the router maker's own app or remote access over mobile data. Test it on the phone with Wi-Fi off. Check
     that remote access is protected by a strong password and, if offered, two-factor login. It opens the
     router's interface to the internet.
   - an always-on device in the home network that is in the tailnet (next section). Then the router is not
     needed at all.

Do not enable an option such as "start this computer automatically when it is accessed from the internet". It
needs a port forwarding, which is exactly what Tailscale avoids.

### Can a switch do it?

No. A switch only passes frames on; it does not send anything by itself (a few managed switches can, but that
is rare). It is not in the way either: it forwards the broadcast to all its ports, the sleeping PC included. If
WoL works with the switch in the path at home (test 3), it also works from outside.

### Always-on device as sender

If the router cannot do it, use any small device at home that is always on and runs Tailscale. For example a
Raspberry Pi, a NAS, or an old Android phone on the home Wi-Fi with Tailscale and a WoL app. With a Pi:

```bash
# once, on the Pi
sudo apt install wakeonlan && curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
# from anywhere, on the laptop
ssh pi wakeonlan -i 192.168.1.255 3c:7c:3f:aa:bb:cc
```

Harden the Pi like the PC (key login only, see [home-pc.md](home-pc.md) §4): it is now the way into your home
network.

### FRITZ!Box VPN (WireGuard) to reach "Gerät starten"

The FRITZ!Box's own WireGuard VPN puts the laptop or phone into the home network, so the router's web interface
(`http://fritz.box`) and its "Gerät starten" button work from outside without opening the interface to the
internet. It cannot join the tailnet: Tailscale uses WireGuard, but with its own key exchange, so the two stay
separate. Use the FRITZ!Box VPN only to wake the PC, and Tailscale for SSH.

- It needs a router reachable from the internet (public IPv4, or IPv6 on both ends). Tailscale does not.
- On the laptop, both can run at the same time if the FRITZ!Box VPN only carries the home network
  (`AllowedIPs = <home network>/24`), not all traffic (`0.0.0.0/0`).
- An unauthenticated WireGuard port does not answer at all, so the open UDP port is a small risk. Keep the
  exported config file private: it contains the key.

Laptop setup: install WireGuard for Windows (https://www.wireguard.com/install/), "Import tunnel(s) from file",
then "Edit": `AllowedIPs` only the home network (remove `0.0.0.0/0` and `::/0`), remove the `DNS =` line (so
Tailscale's names keep working; open the router by IP instead of `fritz.box`). Delete the `.conf` file after the
import; WireGuard keeps its own encrypted copy. Test from outside (phone hotspot): "Activate", open
`http://<router IP>`, home network → network → PC → "Gerät starten", "Deactivate", then `ssh home`.
`uvx wakeonlan` over the VPN does not work (tested 2026-11-15): WireGuard carries only IP packets, and the router
does not pass a broadcast from the tunnel on to the home network (a standard protection against amplification
attacks). Use the button.

### Smart plug as last resort

A smart plug cannot send a magic packet, but with the BIOS setting **Restore on AC Power Loss = Power On**,
switching the plug off for 10 s and on again boots the PC. The plug's app works from anywhere. Use it only to
recover a PC that hangs (e.g. the NVIDIA suspend hang): cutting power is a hard power-off, so never while a run
writes results. Test it once at home. A plug with energy metering shows the PC's state from afar: a few watts
means suspended, a constant idle value with no SSH response means hung. Turn on two-factor login for the plug's
account: it can now switch the PC off.

### Without a sender: scheduled wake-up

Before leaving, let the PC's own clock wake it:

```bash
sudo rtcwake -m mem -t $(date -d 'tomorrow 07:30' +%s)   # suspends now, wakes at 07:30
```

Then it is awake from 07:30, and the idle timer suspends it again after 30 min without a run or SSH connection.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `tcpdump` shows nothing (test 2) | wrong broadcast address, exit node, guest Wi-Fi / client isolation |
| packet arrives, PC does not wake, link LED dark in suspend | BIOS: WoL off or ErP/Deep Sleep on |
| packet arrives, link LED lit, PC does not wake | `Wake-on: d` instead of `g` (NetworkManager setting not applied), wrong MAC |
| works after setup, not after a reboot | NetworkManager setting missing; check `nmcli c show "<conn>" \| grep wake` |
| PC wakes, black screen, `ssh home` fails | hang on resume (NVIDIA driver), see "NVIDIA resume"; or `tailscaled` not reconnecting: `journalctl -b -u tailscaled` |
| wakes from suspend, not from powered off | ErP on, or board does not support WoL from off; suspend is enough here |

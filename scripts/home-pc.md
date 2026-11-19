# Guide: experiments on the home PC

Goal: switch the PC on remotely, start runs over SSH, close the laptop, collect the results later, and have the
PC suspend itself when nothing is running. Read the shared rules in [README.md](README.md) first.

Hardware: i7-6700K (4 cores / 8 threads), CachyOS, wired Ethernet. Laptop: Windows 11.

## How the pieces fit

- **SSH** (Secure Shell) gives you a terminal on the PC from the laptop. The PC runs a server (`sshd`), the laptop
  a client (`ssh`). You log in with a **key pair** instead of a password: the private key stays on the laptop,
  the public key is copied to the PC. Whoever does not hold the private key cannot log in.
- **Tailscale** connects your devices into a private network (a "tailnet") over the internet, encrypted with
  WireGuard. Each device signs in to the same Tailscale account and gets a fixed address (`100.x.y.z`) and a
  name (e.g. `home-pc`). From the library, `ssh home-pc` then works as if you were at home. You do not have to
  open any port on the router, so the PC stays invisible to the rest of the internet. It also works when the
  provider gives you no public IPv4 address (CGNAT/DS-Lite, common in Germany).
- **Wake-on-LAN** switches on a sleeping PC with a "magic packet" sent inside the home network. A sleeping PC is
  not in the tailnet, so the packet has to come from something at home that is always on (usually the router).
- **tmux** keeps a terminal running on the PC after the SSH connection drops. You "detach" from it and "attach"
  again later.
- **`systemd-inhibit`** tells the system "do not sleep while this runs". The idle timer checks for it.

## 1. Laptop (Windows): what to install

| What | Why | How |
|---|---|---|
| OpenSSH client | `ssh`, `scp` | built into Windows 11; check `ssh -V` in PowerShell |
| ssh-agent service | holds the unlocked key, so you type the passphrase once per login | admin PowerShell: `Get-Service ssh-agent \| Set-Service -StartupType Automatic; Start-Service ssh-agent` |
| Tailscale for Windows | reach the PC from outside | installer from https://tailscale.com/download, then sign in |
| Git Bash, `uv` | already installed | for `tar` pipes and `experiment merge` |

Create the key (PowerShell), with a passphrase:

```powershell
ssh-keygen -t ed25519 -C "laptop"        # saves C:\Users\<you>\.ssh\id_ed25519 and id_ed25519.pub
ssh-add $HOME\.ssh\id_ed25519
```

The passphrase encrypts the private key file: a stolen laptop disk alone does not give access to the PC.

## 2. PC: SSH server

```bash
sudo pacman -S openssh tmux
sudo systemctl enable --now sshd
```

CachyOS ships with `ufw` active and no rules, so SSH over the home network (the `enp…` address) is blocked.
That is fine: do step 3 (Tailscale) first and connect to the PC's Tailscale address (`tailscale ip -4` on the PC,
`100.x.y.z`). Copy the public key from the laptop (PowerShell; asks for the PC password once):

```powershell
type $HOME\.ssh\id_ed25519.pub | ssh <user>@100.x.y.z "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**Check the host key on first connection.** `ssh` shows a fingerprint and asks whether to trust it. Compare it with
the PC's own: on the PC, `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Only answer `yes` if they match;
otherwise you could be talking to a different machine.

Now `ssh <user>@100.x.y.z` must log in **without** the PC password. Only then turn passwords off.

### Harden sshd

Keep one SSH session open while you do this, so a mistake does not lock you out. `<user>` here and everywhere in
this guide is your account **on the PC** (`whoami` on the PC), not the Windows user of the laptop. On the PC:

```bash
sudo tee /etc/ssh/sshd_config.d/10-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers <user>
EOF
sudo sshd -t && sudo systemctl restart sshd   # -t checks the syntax first
```

## 3. PC and laptop: Tailscale

```bash
sudo pacman -S tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up                          # prints a link: open it, sign in with the same account as the laptop
tailscale status                           # both devices listed
```

In the Tailscale admin console (https://login.tailscale.com/admin/machines) rename the PC to `home-pc`.

Laptop file `C:\Users\<you>\.ssh\config`:

```
Host home
    HostName home-pc
    User <user>
```

`ssh home` now works at home and outside. Use the normal `sshd` above, not the "Tailscale SSH" feature: one login
path to secure is enough.

## 4. Security checks

Run these once after setup, and again after big updates.

1. **Passwords are refused.** From the laptop:
   `ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password home` must end with
   `Permission denied (publickey)`.
2. **Effective sshd settings.** On the PC:
   `sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|allowusers)'`
   must show `no`, `no`, `no`, `<user>`. (A later file in `sshd_config.d` can override yours; `sshd -T` shows
   what is really in effect.)
3. **No port forwarding on the router.** In the router's interface, no port forward or "exposed host" for the PC.
   Then, from the phone on mobile data with Tailscale **off**, an SSH app or `nc -vz <your public IP> 22` must not
   connect.
4. **Firewall.** `sudo ufw status verbose` must show `Status: active` and `Default: deny(incoming)`. No allow
   rule is needed: `tailscaled` adds its own firewall rules that accept traffic on `tailscale0` before ufw's rules
   are checked, so SSH works over Tailscale (also at home) and stays blocked from the home network. Do not add a
   LAN rule; it would only be a second way in. Tailscale needs no inbound port. It connects outwards.
5. **Tailscale account.** Turn on two-factor authentication at the identity provider you sign in with (Google,
   GitHub, …): whoever holds that account can add devices to the tailnet. In the admin console, check that only
   your devices are listed, and remove old ones.
6. **Who logged in.** On the PC: `journalctl -u sshd --since today | grep Accepted` and `last -n 20`. Only your
   key and your addresses (`100.x` or the LAN) should appear.
7. **Updates.** `sudo pacman -Syu` regularly. `openssh` and `tailscale` are exposed services.

GitHub access from the PC: create a separate read-only **deploy key** on the PC (`ssh-keygen -t ed25519`, add the
`.pub` in the GitHub repository settings → Deploy keys). It can only read this one repository. Avoid agent
forwarding (`ssh -A`): while forwarded, anyone with root on the PC could use your laptop key.

## 5. Waking the PC

Full guide with step-by-step tests, router check and alternatives: [wake-on-lan.md](wake-on-lan.md). In short:

1. BIOS: enable Wake-on-LAN, disable ErP / deep sleep.
2. Network card: `sudo nmcli c modify "<conn>" 802-3-ethernet.wake-on-lan magic`, check `Wake-on: g` with
   `ethtool enp6s0`, note the MAC address.
3. Test at home: the packet arrives (`tcpdump`), then suspend and wake with `uvx wakeonlan` from the laptop.
4. A sender you can trigger from outside: the router, an always-on device in the tailnet, or a scheduled
   wake-up with `rtcwake`.

## 6. Suspending when idle

Desktop power settings only act while someone is logged in at the desktop. A PC woken remotely sits at the login
screen, so `scripts/home/idle-suspend.sh` decides instead. Every 5 min it checks for a running experiment, an SSH
connection, or a desktop session. After 6 idle checks in a row (30 min) it suspends.

```bash
sudo install -m755 scripts/home/idle-suspend.sh /usr/local/bin/
sudo cp scripts/home/idle-suspend.{service,timer} /etc/systemd/system/
sudo systemctl enable --now idle-suspend.timer
systemctl list-timers idle-suspend.timer     # next check
journalctl -u idle-suspend                   # what it did
```

The script recognises the login screen by the user `sddm`. If CachyOS uses another login manager, check
`loginctl list-sessions` and change that name in the script.

Power: suspended, the PC draws a few watts; idling awake with the GTX 1070 it draws far more. For runs, use the
`performance` power profile (`powerprofilesctl set performance`, or the CachyOS equivalent). Watch the CPU
temperature on the first long run (`sudo pacman -S lm_sensors`, then `sensors`).

## 7. Repository and uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # or: sudo pacman -S uv
git clone git@github.com:PaulSeipl/factory-simulation.git ~/simulation
cd ~/simulation && git checkout <hash> && uv sync --frozen   # uv fetches Python 3.14 itself
```

## 8. Starting runs

```bash
ssh home
tmux new -s exp                    # a terminal that keeps running on the PC
cd ~/simulation && bash scripts/home-run.sh
```

Detach with `Ctrl+b`, then `d`, and close the laptop. Later: `ssh home`, then `tmux attach -t exp`.

`scripts/home-run.sh` calls `uv run experiment run`, 4 runs at a time (one per physical core; `JOBS=2 bash
scripts/home-run.sh` for fewer), blocks sleep while they run (check with `systemd-inhibit --list`), and merges at
the end. It skips every run this PC already has a row for (same configuration hash, `host` = this PC), so after
an interruption just start it again. What is left: `uv run experiment list --missing`. Other arguments go to
`experiment run`: configuration names, `--policy <name>`, `--seed <n>` (both repeatable), `--restart` (rerun
also what is done).

Estimate: 25 hindsight runs × 50–80 min ≈ 21–33 CPU-hours, so about 6–9 h on 4 cores for the hindsight runs
alone, longer if the 6700K is slower per core than the laptop.

## 9. Results to the laptop

In Git Bash on the laptop, into a folder of its own (no rsync needed):

```bash
mkdir -p results-home
ssh home 'tar -C ~/simulation -cz experiments/results' | tar -xz -C results-home
uv run experiment merge --out results-home/experiments/results
```

Add `--exclude='*/plans'` to the remote `tar` if only the rows and CSVs are needed.

# JFL Alarm — Home Assistant integration

*[Leia em português](README.pt-BR.md)*

A Home Assistant integration for **JFL Active** alarm panels, speaking the panel's own TCP
push protocol. Domain: `jfl_alarm`.

> **Status: released and in everyday use.** Partitions, the electric fence,
> PGM outputs and zone bypass all work; so do per-zone wireless health and the action layer. Reading
> and writing the panel's full programming is still to come. Issues and pull requests are welcome.

## What it does

The panel **dials out** to Home Assistant — you program a destination IP and port into it, and it
connects and reports. Home Assistant hosts the listener. One listener serves **many panels**, each
identified by its serial number, so several panels of different models can share one instance.

Working today:

1. **The electric fence (eletrificador)** — state and arm/disarm. *This is the primary goal.*
2. **Partitions** — arm away, arm home, disarm, and triggered state.
3. **PGM outputs** and **per-zone bypass**, the bypass switch living on the zone's own device.
   Each PGM shows its programmed function in JFL's own words; an output the panel does not use sits
   in the configuration section rather than among the controls, and the one that triggers the
   electric fence gets no switch at all — the way JFL's own app hides them.
4. **Per-zone health** — each zone is its own device, with battery, supervision and tamper.
5. Panel trouble flags, battery voltage and connection health.
6. Contact ID events as Home Assistant `event` entities — including panic, which changes no status
   byte at all and is therefore invisible to anything that polls. Each event **names who or what it
   was about**: an arm reads *Bruno*, not *003*, and an alarm names the zone.
7. **The panel's own event memory**, on demand — `jfl_alarm.read_event_buffer` returns everything the
   panel recorded, including while Home Assistant was off.

8. **Reading the panel's programming** — the real zone and partition names, and which zones are
   wireless. It happens on its own when a panel connects; **Read programming** and
   `jfl_alarm.read_programming` force it.

Still to come: writing the panel's programming from the Home Assistant UI.

---

## Entities

Everything below appears **only if the panel reports it**. A partition that is not programmed, a
zone that is not in use and a panel with no electric fence produce no entity at all — which is a
different thing from an entity reading "disarmed".

The panel becomes one device, with a sub-device for each partition and one for the electric fence.

### The electric fence

| Entity | Domain | What it is |
|---|---|---|
| `switch.<fence>` | `switch` | **On means armed.** Switching it arms or disarms the energiser |
| `sensor.<fence>_state` | `sensor` (enum) | *Disarmed · Armed · Alarm · Not ready* |
| `binary_sensor.<fence>_alarm` | `binary_sensor` (safety) | The fence is in alarm |
| `event.<fence>_events` | `event` | Fence arm, disarm and alarm events |

**The fence is not an `alarm_control_panel`, deliberately.** That domain has no plain "armed" state
— its armed states are *away*, *home*, *night* and *vacation* — so an armed fence
had to be shown as "Armed away", which an energiser cannot mean. A switch says on or off, and the
state sensor says the rest in the panel's own words. See
ADR-0002.

A cut or broken wire keeps the panel in alarm and **never restores itself**, so the alarm sensor
stays on until somebody clears the fault at the panel.

### Partitions

**One `alarm_control_panel` per programmed partition**, up to the four an Active 32 supports — each an
independent alarm you arm and disarm on its own, which is exactly how a panel split into several areas
("houses") is meant to work. How many appear is detected from the panel: a panel using a single
partition, like the author's, shows one; enable more in the panel and more appear on the next status
frame, with no reconfiguration. A zone belongs to a partition in the panel's own programming; reading
that assignment back into Home Assistant is a later sprint, and needs a capture from a multi-partition
panel to decode (not yet supported).

**The panel's arm modes are on that one entity.** The mapping is not the obvious one, because
JFL's "AWAY" is not Home Assistant's:

| Panel keypad | What the panel does | Home Assistant button | Command |
|---|---|---|---|
| **Armar** | Arms everything. The panel **refuses it while a zone is open** | Arm away | `0x4E` |
| **Armar STAY** | Perimeter only — zones with the *stay* attribute are inhibited so you can stay inside | Arm home | `0x53` |
| **Armar AWAY** | Arms **with** open zones: they are bypassed automatically and return to normal as they close | *not exposed* — see below | `0x54` |
| **Desarmar** | Disarms | Disarm | `0x4F` |

**Home Assistant shows two arm buttons, not three.** The forced arm (*Armar AWAY*) was removed in
2026-08 after being tested on a real panel: the panel reports it back identically to the plain arm,
so a third button did the same visible thing as the first. It is still a valid panel command and
could return as a service if anyone needs it.

Two consequences worth knowing:

- **The panel does not report which of the two full arms was used.** It reads back as *Armed away*
  either way, and both emit the same Contact ID event. Only STAY is distinguishable.
- If "Arm away" appears to do nothing, **a zone is open** — close it, or bypass it with that zone's
  *Bypass* switch, and arm again. The partition's `ready` attribute says so in advance.

> ⚠️ **Upgrading?** An automation calling `alarm_control_panel.alarm_arm_custom_bypass` on a JFL
> partition will start failing rather than silently doing nothing. Switch it to `alarm_arm_away`.

The partition entity also carries a `ready` attribute — the panel's own "no open zones", which tells
an automation in advance whether a plain arm will be accepted.

### PGM outputs

One `switch` per PGM the panel model has — a gate, a garden light, a garage door. The panel decides
which of them a remote connection may operate: only outputs programmed with **function 12** (with
retention) or **13** (without) are, at addresses 821–824. The others still appear, with a
`can_operate` attribute reading false, and switching one produces an error naming the address rather
than doing nothing.

**What each output *does* decides what entity it gets**, and the integration reads that from the
panel — you do not have to tell it anything:

| The output's function | What you get |
|---|---|
| **18** (or 25 on an Active 20) — it triggers the electric fence | **no entity**: the fence is operated through its own switch |
| **0**, *desabilitada* — the panel does not use it | a switch on the panel, under *Configuration*, and **disabled**: it exists, but there is nothing to switch |
| anything else | a switch on the panel, under *Controls* |

> **Why function 18 gets no switch.** It is not the energiser's supply — it is a **momentary
> trigger**, wired to the *LIGA* terminal and pulsed for a second or two to toggle the fence. So a
> switch for it could never be operated (`P-PGM` allows only functions 12 and 13), would read `off`
> for ever between pulses, and could only ever flip the energiser behind the fence entity's back.
> The output is still fully described in the diagnostics download, with its function and duration.
> ADR-0017.
>
> **You never have to identify it.** The programming read that happens on its own when a panel
> connects detects the energiser's output — function 18, or 25 on an Active 20. The **PGM that powers
> the electric fence** setting is only an *override*, for when you know something the programming
> does not; if the two disagree, your setting stands and the clash is raised as a repair.
> ADR-0011.
>
> **The PGM switches therefore appear about half a minute after the rest**, once that read finishes.
> Everything you watch in an emergency — zones, partitions, the fence — is there from the first
> status frame as before.
>
> Each PGM switch also carries its decoded `function`, activation time and schedule as attributes,
> once the programming has been read.

### Zone bypass

One `switch` per zone the panel's programming permits inhibiting, under configuration. On means the
zone is bypassed — excluded from the alarm.

**It lives on the zone's own device**, next to that zone's opening, battery and tamper entities, and
is simply called *Bypass* — the device already says which zone. (It sat on the panel device until
August 2026. Existing installations keep their `entity_id`, history and automations: the entity
moved device, it was not re-created.)

The panel has no "bypass one zone" command: it has "these are the inhibited zones now". So changing
one zone reads the current list back from the panel first and re-sends it with the one change, which
is why inhibiting the garage never releases the zone somebody inhibited at the keypad five minutes
ago. ADR-0006.

Note that a zone the panel auto-bypassed — because you armed with it open — reads as *not* bypassed
here. That is the panel's own behaviour: an auto-bypass is not in the manual list, and it clears
itself when the zone closes. Watch the event entities for `1573` if you need to see it.

### Actions

| Action | What it does |
|---|---|
| `jfl_alarm.sync_time` | Sets the panel's clock from Home Assistant. The panel timestamps every event it reports from its own clock, so a drifting panel files today's alarm under yesterday |
| `jfl_alarm.refresh_status` | Asks the panel for a status frame now. A read, so it works in read-only mode |
| `jfl_alarm.set_bypass_mask` | Replaces the whole bypass list in one command. An empty list clears every bypass |
| `jfl_alarm.read_programming` | Reads the panel's programming and returns it — the zone and partition names above all. A read, so it works in read-only mode, and it never returns a user's access code |
| `jfl_alarm.read_event_buffer` | Returns the panel's own event memory — every arm, disarm, alarm, bypass and trouble it recorded, including while Home Assistant was off, each with its description and the name of the user or zone it was about. A read, so it works in read-only mode |
| `jfl_alarm.send_raw_command` | Sends an arbitrary command and returns what the panel said next. **Administrators only**, and it bypasses every check this integration makes about which commands are safe. It is a reverse-engineering tool |

### Zones, troubles and the rest

| Entity | Domain | Notes |
|---|---|---|
| `binary_sensor.zone_N` | `binary_sensor` (opening) | Open, including while triggering. **Each zone is its own device**, with the four below |
| `binary_sensor.zone_N_battery` | `binary_sensor` (battery) | A wireless sensor's battery is low |
| `binary_sensor.zone_N_connection` | `binary_sensor` (connectivity) | On means the panel is still hearing from it. Off by default |
| `binary_sensor.zone_N_tamper` | `binary_sensor` (tamper) | Somebody is interfering with the detector |
| `binary_sensor.zone_N_fault` | `binary_sensor` (problem) | The aggregate fault, including a short circuit |
| `binary_sensor.<panel>_panel_trouble` | `binary_sensor` (problem) | "Something is wrong", plus one sensor per trouble bit |
| `binary_sensor.<panel>_panel_connection` | `binary_sensor` (connectivity) | **Stays available while the panel is away** |
| `binary_sensor.<panel>_siren` | `binary_sensor` (sound) | The siren is sounding. Read-only, so not a `siren` entity |
| `sensor.<panel>_battery_voltage` | `sensor` (voltage) | The real voltage. The primary battery reading |
| `sensor.<panel>_battery_level` | `sensor` (battery) | A percentage *derived* from it — 10.5 V = 0%, 12.5 V = 100%, clamped. An interpretation rather than something the panel said, so the voltage stays primary |
| `sensor.<panel>_last_connected` · `_last_seen` · `_last_event` | `sensor` (timestamp) | The first two stay readable while the panel is away — that is when they matter |
| `event.<panel>_panel_events` · `event.partition_N_events` | `event` | Every Contact ID event, panel-wide and per partition |
| `button.<panel>_refresh_status` | `button` | Ask the panel for a status frame now |
| `switch.<panel>_allow_commands` | `switch` (config) | **The master gate.** See below |
| `switch.<panel>_pgm_N` | `switch` | One per PGM output the model has |
| `switch.<panel>_zone_N_bypass` | `switch` (config) | One per zone the panel permits inhibiting |

Five zone entities rather than one, and a device each, because the zone nibble encodes six different
things and folding them together would make "open" mean "the battery died".

**Battery, tamper and connection are merged from two sources.** A zone's nibble holds one value, so
a sensor with a dying battery reports "low battery" while closed and "open" the moment somebody walks
past it — the battery is still low, the panel just has nowhere to say so. Contact ID events
`1384`/`3384`, `1383`/`3383` and `1381`/`3381` bracket each condition independently and are latched,
so a low battery survives the door opening. ADR-0008.

### Real names, from the panel

Zones and partitions start as numbers, because the status frame carries no names. Press **Read
programming** on the panel's device page — or call `jfl_alarm.read_programming` — and the panel's own
names arrive: *Zone 3 Cozinha*, *Interno*, *Externo*. Wireless zones also gain the serial printed on
the detector.

It is a button rather than something automatic, deliberately: a full read is thirty-odd round trips,
and a panel that does not answer `0x44` would be asked thirty times on every reconnection. Doing it
on connect needs a probe first — ADR-0010, and it
is planned.

**Nothing here can write.** Sprint 6 reads; `0x45`, the write command, is in no path an entity or a
service can reach. And **no user access code ever leaves the parser** — it reports whether one is
set, never what it is.

Names are nine characters, because that is the field width in the panel.

---

## Safety, and the two gates

This integration controls a real alarm on an occupied house, and it is built to be hard to fire by
accident.

| Gate | Where | Default |
|---|---|---|
| **Read-only mode** | The panel's settings, in the integration's configuration | **On** — the integration observes and sends nothing |
| **Allow commands** | A switch on the panel's device page | On |

**Both must allow a command before anything is sent.** Read-only mode is the deliberate opt-in you
turn off once; the switch is the quick kill switch you can flip from a dashboard, an automation or a
guest-mode script without opening the settings. Either one refusing produces a visible error naming
which it was — a command is never silently dropped.

If the panel itself refuses an operation (its programming does not grant it to a monitoring
connection), the error names the panel address to check rather than failing silently.

### The optional code

You can set a **code that Home Assistant asks for** before disarming, and optionally before arming
too. It is empty by default, and it is entirely optional — the panel's own keypad already has one.

- It is a **Home Assistant** code. It is never sent to the panel and has nothing to do with a panel
  user code.
- Disarming always asks for it once one is set; asking on the way *out* as well is a separate switch.
- It protects the partition entities. **The fence switch cannot ask for a code** — the `switch`
  domain has no code field — so if you want the fence behind a confirmation, use a Lovelace
  confirmation on the button or an automation.

### No password ever reaches the panel

The whole command set this integration uses (`0x4E`, `0x4F`, `0x53`, `0x54`, `0x4D`) carries **no
password**, which was confirmed by capturing JFL's own ActiveNet software driving a real panel. The
password-authenticated family is deliberately not wired up: five wrong passwords block remote
operation at the panel until somebody performs a valid keypad operation, and nothing here needs it.
If a panel ever answers with "wrong password", the integration stops immediately and raises a repair
issue.

### Nothing is optimistic

An entity never shows a state because a command was sent. Commands are followed by two status
re-reads, and the panel's own answer is what you see. This matters more than it sounds: in the
reference capture, arming returned a status frame that still showed a zone open, and the panel
auto-bypassed it a second later.

## Supported panels

| Model byte | Panel | Partitions | Zones | PGMs | Fence | Verified on hardware |
|---|---|---|---|---|---|---|
| `0xA0` | Active 32 Duo | 4 | 32 | 4 | yes | **Yes — firmware 7.60** |
| `0xA1` | Active 20 Ultra / 20 GPRS | 2 | 22 | 4 | yes | No |
| `0xA2` | Active 8 Ultra | 2 | 12 | 0 | no | No |
| `0xA3` | Active 20 Ethernet | 2 | 22 | 4 | yes | No |
| `0xA4` | Active 100 Bus | 16 | 99 | 16 | yes | No |
| `0xA5` | Active 20 Bus | 2 | 32 | 16 | yes | No |
| `0xA6` | Active Full 32 | 4 | 32 | 16 | no | No |
| `0xA7` | Active 20 | 2 | 32 | 4 | yes | No |
| `0xA8` | Active 8W | 2 | 32 | 4 | yes | No — and see the note below |
| `0x4B` | M-300+ | 0 | 0 | 4 | no | No |
| `0x5D` | M-300 Flex | 0 | 0 | 2 | no | No |

**Only the Active 32 Duo has been tested against real hardware.** Every other model is implemented
from JFL's specification and is exercised in tests against a simulator, which is not the same thing.
If you own one, a report either way is welcome.

The Active 8W is doubly uncertain: JFL's own ActiveNet software places it on a **different protocol
generation** (`0x7A`, two-byte length) that this integration does not implement. Expect it not to
work.

## Setting it up

1. Add the integration. The only question is the **TCP port to listen on** — everything else is read
   from the panel when it connects.
2. Program the panel to report to this machine's address and that port, on a **free** reporting
   destination. Do not overwrite the slot your monitoring company uses; enable dual reporting at
   address 700, TECLA8, so both keep working.
3. The panel appears on its own within a minute or so, with its partitions, zones and fence.
4. To operate it, open the panel's settings and turn **read-only mode** off.

If nothing appears after fifteen minutes, the integration raises a repair notice with this checklist
— an integration the panel has to connect *to* fails silently by nature, and that notice is the fix.

## Installation

Install through [HACS](https://hacs.xyz) as a custom repository:

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/jmceara/jfl_alarm` — category: **Integration**
3. Install **JFL Alarm**, restart Home Assistant, then add it from
   **Settings → Devices & Services → Add Integration**.

The panel dials *out*, so nothing needs to be reachable from the internet: program the panel's
reporting destination with this machine's LAN address and the port you choose (9494 by default).

All frame handling lives in [`pyjfl`](https://pypi.org/project/pyjfl/), an independent package
Home Assistant installs automatically.

## Screenshots

![Integration details](docs/screenshots/05_jfl_integracao_detalhes.png)
*The integration's own page — devices, entities and status once a panel has connected.*

![Options dialog](docs/screenshots/06_jfl_opcoes_modal.png)
*The configurable options: network port, passwords, timeouts.*

![Panel and its sub-devices](docs/screenshots/11_central_sub_dispositivos.png)
*The panel device with its linked sub-devices — zones, partitions and PGMs grouped underneath it.*

![Wireless zone device](docs/screenshots/12_dispositivo_sensor_sem_fio_zona9.png)
*A wireless zone's device page: open/closed state, signal strength, battery and last transmission.*

![Wired zone device](docs/screenshots/24_dispositivo_zona_8_ecr.png)
*A wired zone's device page, with its bypass switch and diagnostics.*

## Credits

**Author:** Jonis Maurin Ceará — jmceara AT gmail.com

**Based on** the work of **Carlos Jose Fernandes**, <https://github.com/fernac03/JFL_ACTIVE>. This
is a new implementation, but it stands on that one: the original is the record of what actually
operates a live JFL panel, and its packet offsets, model table and command frames informed this
work. See AUTHORS.md.

The protocol is implemented from JFL's own published specifications and from observing JFL's
official ActiveNet software communicating with a panel.

*Not affiliated with or endorsed by JFL Alarmes.*

### Wireless detector health

Every zone with a radio detector gains, once the panel's programming has been read:

| Entity | What it says |
|---|---|
| **Signal** | The link quality, in the panel's own four steps — *Excellent*, *Very good*, *Good*, … Attributes carry the **repeater** it arrives through (`0` = direct), its **firmware** and its **serial** |
| **Last transmission** | When that detector last spoke, as the panel recorded it |

The detector's **model** — *IRD-650 DUO*, *SL-220 DUO* — appears on the zone's device page.

These come from the panel's wireless inventory, which is a separate request from a programming read;
the enrolment table says a zone *has* a radio device, the inventory says what condition it is in. A
detector that drops out of the inventory reads *unavailable* rather than showing a stale signal.

### The panel's timers

Eight diagnostic sensors, **each in its own unit** — entry, exit and the smart-zone window in
seconds; open-door, mains-loss and line-loss in minutes. A timer the installer disabled reads
*unknown*, not `0`.

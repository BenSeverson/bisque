# Design notes

Until 2026-10-06 the board's connectivity, placement and part identity lived
in `generator/design.py`, and the engineering reasoning behind each choice
was written as comments beside the table entries. The table is gone: the
schematic (`bisque-controller.kicad_sch` and `sheets/`) owns connectivity
and part identity, the board file owns placement, and `make pcb-sync` is
the bridge. The reasoning is kept here, verbatim, one section per block
of commentary, headed by the reference designator it was written beside.
Line numbers refer to `design.py` at commit f4c5523, the last that carried
it, for anyone who wants the original context.

Some sections mention tables that no longer exist (`gen_pcb.ROUTE_ORDER`
still does; `floorplan.py`, `apply_floorplan.py` and the `at=` tuples do
not). Read those as history. The decisions - why a part is what it is, why
it sits where it sits, what was tried and rejected - are what this file is
for, and they still hold.


## Pin map and power path (module docstring)

```

Components, pin->net connectivity, and PCB placement. Both the schematic and
board generators derive everything from these tables, so the two files can
never disagree on connectivity.

Which GPIO each net lands on is NOT written down here: U1's labels in the
schematic own it, main/Kconfig.projbuild owns the firmware defaults, and
docs/pin-assignments.md §1 is the one table for reading (check_pinmap.py holds
all three together). What the nets do:
  BTN: the five nav buttons sit on contiguous module pads (moved off ADC1 in
    Task 3).
  AUX bank (U6, ULN2003): AUX1 (vent) / AUX2 / AUX3 on terminal J10 with the
    external AUX_VP coil rail (SJ1 links it to +5V).
  Touch (Task 11): T_CS / T_IRQ are dedicated GPIOs; T_CLK/T_DIN/T_DO are the
    shared SPI2 bus (SPI_SCLK/SPI_MOSI/SPI_MISO) through series resistors.
  I2C: I2C_SDA / I2C_SCL — shared bus, pulled up on-board, broken out on
    both J7 (0.1") and J14 (Qwiic/STEMMA QT).
  Watchdog: WDT_KICK retriggers the U10 one-shot; its Q holds Q3 on, Q3
    holds SSR_PG down, which turns on the high-side switch Q4 supplying
    SSR_EN. SSR_EN is a +5V GATE-DRIVE rail, not the terminal supply: it
    enhances Q7, which pulls the gate of the 24 V cutoff Q9 down, and Q9
    feeds SSR_24V to both channels (rev B.4). SJ2 ("WDT DEFEAT") shorts
    SSR_PG to GND for bring-up only.
  J11: IN1 (lid), IN2 (gas flow), IN3 (spare).
  SSR drive (rev B.4): each terminal's + pin is SSRn_OUT, switched by a
    60 V P-channel LP2309LT1G (Q5/Q6) off SSR_24V; the - pin is board GND.
    The GPIO drives an opto LED (U8/U9) whose transistor pulls the gate
    down; an 8.2 V zener per gate sets V_SG from the rail. SSR_24V is VIN_P
    through Q9, the watchdog's high-side cutoff. Opto = containment, not
    isolation: rev B's opto-isolated version was reverted and that reasoning
    still stands. See the SSR block below.
  Power path: J2 -> F1 -> D8 (clamp) -> Q8 (reverse polarity, a P-FET and no
    longer a diode) = VIN_P, which feeds the buck AND both SSR terminals.
    U11 makes BUCK_5V; U12 selects between BUCK_5V and USB VBUS to make +5V,
    in PRIORITY mode so the buck wins over a higher USB port rather than the
    other way round; U2 drops +5V to +3V3. BUCK_5V and +5V are separate nets
    on purpose - C44/C46 belong to the buck's feedback loop and stay on
    its side of the mux. See the Q8 and U12 blocks for both derivations.

J7's pins 5-8 carried VENT/(unconnected)/AUX_A/AUX_B through Task 10, all
either dangling single-pin nets or declared-but-undriven — nothing on this
board actually sourced them (the real VENT output is AUX1, wired to the
ULN2003 aux bank, U6). Task 11 re-points J7 5-8 to I2C_SDA/I2C_SCL/+3V3/GND,
retiring the AUX_A/AUX_B nets for good and giving the I2C bus a 0.1" header
alongside the Qwiic connector (J14). IN1/IN2/IN3 (Task 9) land on their own
terminal, J11, not J7 - rev A's lid switch was the only occupant of J7.6 and
has moved there. Note that an enabled-but-unwired IN1 (lid) reads open and
holds the SSR off - it needs a switch, a jumper to GND, or -1. The full
as-built map, the constraints behind it, and the planned expansion live in
docs/pin-assignments.md — keep that table in sync with this one.
```

## general (design.py line 52)

--- board outline (mm, page coords) ---
100 x 100 mm, 4-layer - spec 6.3 rung 3 (measured outcome). The 2-layer
escalation ladder never closed: 100x100/0805 (rung 0) left 34 nets
unroutable, 100x100/0603 (rung 1) left 23, and 125x100/0603 (rung 2) left 9
short local nets boxed in by neighbours' copper in the SSR driver cluster
and the ADE7953 block - the signature of a layer shortage, not an area
shortage. Going 4-layer (rung 3: GND plane on In1.Cu, +3V3 plane on In2.Cu)
closed it at 0 unrouted/0 DRC errors, and then gave back every rung-1/rung-2
concession: the board walked back to 100 x 100 mm, 0805 passives, and rev
A's 0.3 mm signal / 0.7-0.8 mm rail widths, staying inside JLCPCB's
<=100x100 promo tier. Those widths live in gen_pcb.ROUTE_ORDER, and
gen_pcb.netclass_table() derives the .kicad_pro net classes from that same
table - for a long time this comment said "net classes" while the project
file held one Default class at 0.2 mm and no patterns at all.
See the task 14 report for the DRC counts at each rung.

## general (design.py line 69)

Placement regions. DESCRIPTIVE, not enforced - nothing checks a part against
a band, so this block is only worth what its accuracy is worth. Measured off
the placement below rather than copied forward from spec §6.2, because the
spec's version had stopped being true:

digital    x 20..120  y 20..48   module, USB-C, power in, RESET + BOOT
switching  x 20..60   y 48..95   ULN2003, SSR drivers, watchdog, buzzer
analog     x 88..120  y 33..92   MAX31856 x2 (north), ADE7953 + CT (south)
headers    x 20..120  y 94..120  LCD / nav / aux / I2C, input terminal
(unzoned)  x 60..92   y 48..94   buzzer driver, TP4-TP10, status LED,
the nameplate

Two corrections against §6.2, both found by measuring:

The analog region is a COLUMN spanning y 33..92, not the y 50..92 box the
spec drew, and it does not "hold both thermocouple cold junctions" in the
quiet band - U3 sits at y 37.8 and U5 at y 49.8, i.e. the TC front-ends are
level with the digital band and always were. That is tolerable rather than
intended: the east end of the digital band holds only R2 and the two
buttons, so it is quiet in practice, and every low-level terminal (J3, J8,
J12) still lands on the east edge while every mains-side one (J2, J4, J9,
J10) lands on the west. That west/east split is the property this floorplan
is actually built on and it does hold - ~30 mm separates the SSR/ULN2003
cluster from the front-ends.

The 32 x 46 mm band between the switching column and the analog column
belongs to no region at all. It is the lowest-density area on the board
(~1.1 parts/cm2 against 2.30 in the analog column), which is why the
nameplate search (gen_pcb.largest_empty_rect) keeps landing in it, why the
WS2812 status cluster moved into it, and also why the ADE7953 block, boxed
in at 2.30, had to push its crystal 19.5 mm south. If something needs room,
this band is where the room is.

But do not mistake it for the ONLY room, and above all do not mistake the
band just south of the module (x 60..88, y 44..56) for room at all. It
measures emptier than anywhere else on the board and it is the escape path
for forty castellated pads: putting the status LED there cost SPI_MOSI and
SPI_SCLK their test-point terminals and left TC1_CS unrouted. Clear board
beside a big part is not free board.

There is no isolation-barrier region, and U8/U9 coming back in rev B.2 did
NOT bring one with them. The four-layer pour keepout that used to reserve
x 20..40.8 / y 71..95.5 belonged to the opto-ISOLATED design, which was
reverted and stays reverted; the optos are back as a containment part in
ordinary pour and routing area. See the SSR block below before adding a
keepout on their account.

## general (design.py line 116)

net name -> netclass ("signal" default).
AUX_VP is an externally supplied coil rail the board does not generate, so
it may not join the GND/power pour logic. SSR_EN is board +5V switched by
the watchdog's high-side MOSFET - a driven rail, but a gated one, so it is
deliberately not a pour net either; SSR_24V (rev B.4, VIN_P through Q9) is
gated the same way and stays a 0.6 mm track for the same reason.

## general (design.py line 123)

---------------------------------------------------------------------------
Components
---------------------------------------------------------------------------
ref: (lib, symbol, fp_lib_id, fp_file, value, (pcb_x, pcb_y, rot), {pin: net})
net None => explicit no-connect

## general (design.py line 129)

Chip passives are 0805, same as rev A (spec 6.3 rung 3, walked back from
the 0603 the 2-layer escalation ladder tried at rungs 1-2). Rev B put 2.7x
rev A's part count on the same 100x100 area; on 2 layers even 0603 at
125x100 left nine nets unroutable, and going 4-layer closed the board
without needing the smaller passives at all - see the task 14 report for
the DRC numbers at each rung. 0603 and 0805 are both JLCPCB *Basic* sizes,
so the walkback cost no feeder fee and no assembly tier. The names below
(R0603/C0603) are historical from the rung-1 attempt; the footprints they
point to are 0805. The 22 uF/25 V bulk capacitors stay 1206 - that
value/voltage is not a Basic part in 0603 or 0805, and neither sits in a
congested area.

## general (design.py line 143)

SSOP-8 (TI's DCT package), not the VSSOP-8 the same die also ships in. Two
reasons, and the second is the one that decided it:
- Pitch. VSSOP's 0.5 mm land leaves 0.150 mm between adjacent pads and this
board's net classes require 0.200 mm, so that footprint is twelve DRC
violations before a single track is routed. SSOP-8 at 0.65 mm gives
0.350 mm - more margin even than TSSOP-8's 0.250 mm.
- Datasheet basis. The window arithmetic below is TI's (SCES586E): the
K = 1.0-1.1 constant at the 10k x 0.1uF anchor, the +-0.25 uA Rext/Cext
leakage, the -40..125 C table. C123302 is that same TI die in a different
package, so the numbers carry over unchanged. A Nexperia 74LVC1G123 is a
different datasheet and would need the window re-derived from it.

## general (design.py line 157)

--- thermocouple channel geometry ---------------------------------------
The two MAX31856 front-ends are one circuit placed twice, and this is the
table both copies are written against: TC1_Y / TC2_Y are the chips' own y,
every other part in a channel is `TCn_Y + <its offset>`, and the two
channels use the SAME offsets with the sign flipped, because the two chips
are MIRRORED.

The mirror is the part worth explaining, because "make both parts face the
same way" is the obvious instinct and it was tried and reverted here.

U3 is rot 270 and U5 is rot 90 - a 180 deg flip, which on a TSSOP swaps
which row every pin is on. So U3's digital row (pins 8-14: SPI + chip
select) faces SOUTH and U5's faces NORTH, and the two look at each other
across a 6 mm channel at y 41..47. The whole SPI bus lives in that channel:
three bus nets plus two chip selects, one lane, both chips reached without
leaving it. Turn U5 to match U3 and its digital row moves to y 52.7, which
drags the bundle 6 mm south into the ADE7953's own escape corridor - and
that corridor has no room. Measured, three times: `I2C_SDA` could not reach
U7's SDA escape at (94.5, 68) and the board finished with 4 unconnected
pads. It failed even when promoted to route FIRST, so it is a geometry
problem, not an ordering one.

What the mirror genuinely cost was NOT the rotation. It was that channel 2's
parts had been placed on channel 1's offsets un-mirrored, so U5's analog
inputs (pins 1-7, south) sat on the OPPOSITE side of the package from their
own 100R/100nF/10nF input filter (north, level with the digital row).
Channel 2's differential pair left the filter, ran the length of the chip
past SPI_SCLK/MOSI/MISO and the chip select, and came back - on an input
where 40 uV is a degree. Mirroring the filter with the chip fixes that and
keeps the SPI channel; it is what TC2_DY exists to enforce.

What the mirror still costs, and this is the residue: the supply pins sit
on the far side from the x=90 decoupling column, 9.0 and 7.7 mm out against
channel 1's 6.4 and 5.1. Moving those two caps east would fix it and puts
0805s in the SPI channel, which is the one thing this whole arrangement
exists to keep clear. On a ~100 SPS sigma-delta with no fast edges, leave
it.

Nothing in the netlist can catch any of this: connectivity is identical
whichever way a chip faces, which is exactly why the geometry is derived
here instead.

## general (design.py line 202)

--- SSR channel readout geometry ----------------------------------------
Same idea, for the thing a person standing at the kiln actually reads: each
SSR channel's amber indicator and its control test point sit on ONE row,
the two rows 8 mm apart, and the two test points share an x. So LED3/TP9
name channel 1 and LED4/TP10 name channel 2 by being level with each other,
and the pair of test points is a pair you can get two probe tips onto.

They used to be scattered across the switching block - LED3 (57.0, 76.0),
LED4 (54.0, 87.5), TP9 (58.5, 80.5), TP10 (44.5, 94.15) - on four different
y and three different x, 14.2 mm apart, with TP10 close enough to J5's pin
row that its `SSR2` legend needed a hand-written override to stop reading
as a fifteenth display pin (see gen_pcb.TP_LABEL_AT, now empty).

## general (design.py line 228)

The five nav buttons on pins 31-35 map straight across to
J6.1-J6.5, and that mapping has all five nets crossing all
the others - pins 31-35 are a column at x 78.75 and J6's pins
a row at y 104, opposite sides of the region, so the NESTED
matching is the planar one. Reversing it was tried and
REVERTED, and the measurement is the reason: the two
matchings have the same total ideal length to within 0.2 mm
(353.0 vs 352.8), the rebuild came out 2.7 mm LONGER over two
fewer vias, and both figures are inside the noise of an
unrelated reshuffle. The crossings are nearly free because
the sources span 5 mm of column against a 70 mm run: the five
nets are almost parallel whichever way they are paired, and a
crossing between near-parallel tracks costs a layer change,
not length. Not worth a Kconfig re-map. Keep in step with
main/Kconfig.projbuild and docs/pin-assignments.md -
check_pinmap.py asserts the first two agree and CI runs it.

## J2 (design.py line 258)

--- Power -----------------------------------------------------------
The board makes its own 5 V rail from a 24 V input (U11 below). Two revs
ago it took 5 V directly and +5V was literally VIN minus a series
Schottky, so every drop and every turn of the installer's trim pot
landed on the WS2812B threshold, the SSR drive and the relay coil at
once. Regulating after the protection is what stopped that, and this
rev finishes the job by taking the drop out of the protection as well:
reverse polarity is now Q8, a P-FET at ~33 mV, and the USB OR is U12,
a power mux at ~40 mOhm. Between them they deleted the board's last two
series diode drops, on the two rails least able to spare one.

The protection cluster stays HERE, at the entry, not beside the buck -
a TVS placed at the load protects only the load. The 24 V run east to
U11 is the cheap direction to send power: ~0.25 A against the ~1 A the
same load costs on a 5 V rail.

## F1 (design.py line 276)

Review C item 1, scaled to the new input. The review named an SMAJ5.0A,
which on a 24 V rail is a permanent short - a 5.0 V standoff breaks down
at 6.4 V. F1+D8 are the same clamp-and-blow pair at the right voltage:
D8 defines the clamp, F1 ends the event. Neither works alone - a 400 W
TVS is rated for a 10/1000 us pulse, not for holding a DC fault, and a
PPTC on its own is far too slow to protect anything from the voltage.

Ratings are picked against each other and against U11's 40 V abs max.
D8 stands off 30 V (above an HDR-15-24 at the top of its trim range,
29 V - the Mean Well sheet says 21.6-29 V, not the +-10% this note
used to assume) and breaks down at 33.3 V min, so a SUSTAINED fault
sits at 33-37 V, inside U11's rating. Its 48.4 V clamp at 8.3 A does
exceed 40 V, but that is a surge figure and an abs-max is a DC spec. F1
must survive the fault voltage MINUS the clamp, so its 33 V rating
covers inputs to ~67 V. 750 mA hold against a ~250 mA load leaves room
for inrush without nuisance tripping, and its 90 mohm sits upstream of
a regulator.

--- THE ENVELOPE, 2026-10-27 (schematic review 2026-10-05 item 1, PCB
review item 9). The reviews were right that "it is a surge figure" is
not a rating, so here is what the clamp is coordinated AGAINST, with
numbers. The 24 V input is the HDR-15-24 (or a supply of the same
class: <= 1 A current limit) inside the same enclosure, on wiring that
stays in the box. It is not a field port and claims no IEC 61000-4-5
surge rating. Under that envelope the SMAJ30A's own table gives the
rail: dynamic resistance (48.4 - 36.8)/8.3 = 1.4 ohm, so VIN_F sits at
36.8 V + 1.4 V per ampere, worst case.
  (a) Supply regulation failure. The HDR-15-24 limits at 110-145% of
      15 W, i.e. <= 0.91 A: rail <= 38.1 V. D8 cannot hold 33 W and
      fails SHORT, the supply sees < 50% output and hiccups. Nothing
      downstream saw more than 38 V. The board needs a new D8.
  (b) The supply's own OVP, 30-36 V, overlaps D8's 33.3-36.8 V
      breakdown. Either the supply shuts off first or (a) happens.
  (c) A larger supply misapplied. F1 trips above 1.5 A; up to 2.3 A the
      rail stays under 40 V, and D8 fails short well before F1's
      seconds-long trip at that current, so F1 then clears a dead short.
      Only at 5.8 A would the rail reach U11's 45 V abs max, and only a
      10/1000 us pulse at 8.3 A reaches the datasheet's 48.4 V.
So the parts behind D8 are sized for 38 V sustained and 40 V transient,
not 48 V. Q8 (AO3401A, 30 V) is NOT in that list: its body diode
conducts from the first microsecond and D11 clamps its gate, so it
stands off nothing in a forward fault (the Q8 note below). The two that
HAD no margin were the 40 V diodes - D7's SS34 and D9/D10's B5819W,
both of which see the rail in reverse - and both are 60 V-class or
better now (see D7 and D9). The reviewers' lower-clamp option is ruled
out by the supply: an SMAJ28A stands off 28 V, under the 29 V trim top.
The remaining exposures are named, not fixed: the external SSR input
must take 29 V and survive 38 V (installation check A4), and a true
field-surge rating or a 60 V buck is rev C work.

## Q8 (design.py line 298)

--- REVERSE POLARITY: a P-channel MOSFET, not a diode ----------------
D1, an SS34 in series with the rail, was here and was the obvious part
for the job right up until VIN_P stopped being a 250 mA net. It now
feeds the buck AND both 24 V SSR terminals, whose budget below is
400 mA, so at the fuse's 750 mA hold the diode burned 0.4 V x 0.65 A =
260 mW in an SMA. Q8 burns 0.65^2 x 60 mOhm = 25 mW and drops ~39 mV,
taking the AO3401A's GUARANTEED 60 mOhm at V_GS = -4.5 V rather than
the 47 mOhm typical or the 50 mOhm it reaches at -10 V, because -4.5 V
is the datasheet's lowest spec point still below D11's clamp. Same
protection, ~235 mW back, and the SSR block no longer has to spend a
paragraph excusing a terminal voltage of "24 V minus a diode".

SOURCE on the LOAD side (VIN_P), DRAIN on the SUPPLY side (VIN_F), gate
pulled to GND. That orientation is the one that reads backwards and it
is not negotiable: a P-channel body diode runs drain->source, so with
the drain on the supply it conducts the instant power arrives and the
FET then enhances itself from the V_GS that appears across it. Wire the
part the intuitive way round and the body diode faces the supply, which
conducts a reversed input straight into the board and protects nothing.

WHY 30 V IS ENOUGH HERE WHEN IT WAS NOT FOR Q5/Q6/Q7. The SSR block
buys 60 V CJ2310s because those switches stand off a sustained fault at
the 33-37 V D8 clamps it to. Q8 never stands off anything like it, in
either direction, and the two reasons are different:
FORWARD - the body diode clamps V_DS to one drop from the first
microsecond, before the gate has charged at all. The part never
blocks the input voltage, not even during a fast ramp or a fault.
REVERSE - a reversed input forward-biases D8, which holds VIN_F at
about -0.8 V. Q8 stands off well under a volt.
It is also not a free choice. The whole fee-free library holds exactly
one P-channel part above 30 V - an LBSS84, 130 mA and 10 ohm, which
cannot carry this rail at all - so a 60 V P-FET here would be a feeder
fee to solve a problem the body diode and D8 already solve. AO3401A is
Q4's part, already a BOM line and already Basic: this swap adds none.

R62 turns it on; D11 is what stops R62 destroying the gate. At 24 V an
unclamped V_GS is twice the AO3401A's +-12 V rating. 100k against the
zener's ~7.5 V at this current draws (24 - 7.5)/100k = 165 uA, i.e.
4 mW against the diode's 260 mW. 8.2 V and not 10 or 12 V because the
tolerance stacks the wrong way - a 12 V part at +5% is 12.6 V, outside
the rating it exists to guard - while 7.5 V at the low end still clears
the -4.5 V spec point where the AO3401A guarantees 60 mOhm, which is
the number the loss above is taken at.

Pin order from KiCad's Transistor_FET:AO3401A symbol, as for Q4:
1 G, 2 S, 3 D.

## R62 (design.py line 347)

R62 and D11 sit SOUTH of Q8, not in the free column west of it, and
that column is the reason. J2's two screws are the board's only
per-terminal polarity marks, and the strip between J2's body (x 31.71)
and whatever is east of it is the only place `-` can legally print at
its screw's y of 44.08 - a 1.32 mm glyph needing the whole gap. An 0805
parked there is silk-clean by DRC and still buries the mark inside the
connector, which is exactly the failure the U2 row was shifted 1.5 mm
east to fix (see U2). The first placement of R62 did it again, and
silk.py caught it as "board text '-' sits on a part body".

## U12 (design.py line 366)

--- +5V SOURCE SELECT: a power mux, not an ORing diode ---------------
D2, an SS34 from VBUS to +5V, was here. It did three jobs and did one
of them expensively: it let USB power the board with no 24 V present,
it stopped the buck back-driving a host, and - because a diode drops -
it handed the buck priority whenever both were live, for free. The cost
was 0.4 V off the USB path, and that 0.4 V is the whole reason U2 has
to be a TLV1117LV. See U2 below: the conclusion there does not change,
but the arithmetic reaching it does, so it is restated there.

U12 does all three jobs across ~40 mOhm rather than a diode drop, and
adds the one this board actually needed: it blocks reverse current INTO
the unpowered buck. Today every USB-only bench session - which is every
flashing session - parks 5 V on U11's output, back-feeding FB (pin 3)
and, through L1, the switch pin, both rated only to V_IN on a part
whose V_IN is 0 V at the time. That is fab-review finding C1 and this
is its fix, so the measurement it asked for on board 1 is moot.

PRIORITY MODE, NOT HIGHEST-VOLTAGE-WINS, AND THE DIFFERENCE IS THE
POINT. An ideal diode or a plain ORing controller passes whichever
input is higher, and a 5.25 V USB port is higher than a 5.0 V buck - so
a laptop would end up sourcing the relay bank and both SSR terminals.
The diode gave the buck priority by dropping; U12 has to be told. MODE
ties to VIN1, so pins 3 and 5 are both BUCK_5V - one net with two
terminals, nothing for the router to strand on a private MODE stub -
and R63/R64 divide BUCK_5V into PR1. Above VREF the buck wins whatever
USB is doing.

30k/10k sets the switchover at 4.0 V nominal, and that value is pinned
from BOTH ends rather than rounded to:
TOO HIGH and the buck loses its own priority. VREF is 0.92-1.08 V, so
the real threshold is 3.68-4.32 V; against a buck 4% low (4.8 V)
the worst corner still reads PR1 = 1.20 V against a 1.08 V VREF.
33k/10k - the obvious 4.3 V divider - leaves 36 mV at that same
corner, which is not a margin.
TOO LOW and THE RAIL SAGS TO THE THRESHOLD before USB takes over.
Pull the 24 V with USB plugged in and +5V tracks BUCK_5V down until
PR1 crosses VREF: the threshold IS the floor of that dip. 10k/4.7k
needs no new BOM line and puts it at 3.13 V, under U2's dropout -
so a bench supply switched off would brown out the ESP32 on the way
to the USB rail it was about to reach. 3.68 V worst case clears U2
(3.3 V + 90 mV at 200 mA) by 290 mV.
The switchover is break-before-make and ~8 us, over which +5V's own
ceramics (C1 22 uF + C11 10 uF + C2, ~25 uF after DC bias) droop
0.3 A x 8 us / 25 uF = ~100 mV - so the dip depth is set by the
threshold and essentially nothing else.

Coming back the other way dips too, and by the same amount. When 24 V
returns with USB attached, PR1 crosses VREF while BUCK_5V is still at
the 3.68-4.32 V threshold, below the ~5 V USB is holding +5V at. U12
opens both channels and will not close channel 1 until +5V has
discharged to BUCK_5V + V_RCB (42-70 mV) - TPS2116 SLVSFG1A s7.6.1 -
so the rail falls to the threshold on the way UP as well, and the buck
is never back-driven. (An earlier note here said U12 waits for BUCK_5V
to rise past VOUT; the datasheet says it waits for VOUT to fall.)

MODE with the buck absent is also settled by the datasheet rather than
by the topology: MODE = BUCK_5V = 0 V reads as manual mode (<= 0.35 V),
PR1 is low, and s7.6.1 passes "the higher voltage supply between VIN1
and VIN2" - USB. That is what makes USB-only bench power work at all.

ST (pin 8) IS DELIBERATELY UNCONNECTED, and it is the one thing here
worth reopening in a later rev. It is an open-drain "running on VIN2"
flag, and a kiln controller that refuses to start a firing on bench
power is a real feature. The only free GPIO is on module pin 30
at x 78.75 - the far side of U1 - so the net would have to cross the
castellated escape band at x 60..88, the band that cost SPI_MOSI and
SPI_SCLK their test points the last time anything was routed through
it. Not worth a strandable net for a flag no firmware reads yet.

PLACEMENT, AND IT IS NOT JUST A COURTYARD PROBLEM. SOT-583-8 is a
0.5 mm-pitch part, so it belongs in gen_pcb.FANOUT with U7/U3/U5/U10
for exactly the reason documented there: the front layer between
0.5 mm-pitch pads is entirely clearance, via-in-pad is forbidden, and a
pad with no seeded lane cannot start a route at all. Left out of the
table it fails precisely the way U10 did - "0 goal node(s), free
neighbours F/B=0/0" on VBUS, +5V and BUCK_5V, which is what the first
attempt at this part did on pass 1.

ROT 180, NOT 0, AND THE FANOUT IS THE WHOLE REASON. all_seeds() sends
each pad out along whichever axis its offset from the part centre is
larger on. This footprint is 1.48 mm across the columns and 1.50 mm
along them, so the four CORNER pads escape vertically and the four
middle pads horizontally - a 0.01 mm margin deciding a direction. At
rot 0 the two corner pads that carry a net are PR1 and MODE, and they
escape SOUTH: 1.75 mm from y 36.95 lands at y 38.7, straight through
the USB pair. At rot 180 those two are at the north edge instead and
escape into the open band above, while GND (a plane net, via not stub)
and the unconnected ST take the south corners where a stub would be a
problem. The horizontal pairs then fall out right as well: VBUS and
+5V leave west toward U4/J1 and U2, BUCK_5V and +5V leave east.

The USB pair's own constraint still holds and is now met with room to
spare: C3's north edge pins the pair's centreline at y 38.0 until it is
past C3, the pair needs 1.2 mm, so anything here must end above y 37.4.
The SMA ended at 37.25 with 0.15 mm of slack and the router still chose
to thread the pair BETWEEN its two pads, under the body. This part's
pads end at 36.95 and its courtyard at 37.50, and nothing of it reaches
into the lane, so the pair can simply run south of it.

R63/R64 are NOT beside the part, and that is deliberate: the west
escape corridor (two stubs at y 35.95 and 36.45 running out to x 52.5)
has to stay empty, and an 0805 anywhere in D2's old footprint sits in
it - the first attempt put R63 at x 52.5 and its pad landed 0.20 mm
from the VBUS stub. They go instead in the band north of R4 (x 54.7 to
60, y 29.8 to 32.6), which is the largest genuinely free area in this
quadrant, both rotated so their MUX_PR1 pads share y 32.31. That makes
PR1 a straight 2.4 mm run with U12's own PR1 stub ending 0.7 mm off it,
and hands BUCK_5V the detour around R63 - the right way round, because
PR1 is a 0.3 mm signal routed LAST while BUCK_5V is a 0.7 mm rail
routed fourth, into an empty band.

ONE THING THE DIODE USED TO DO THAT U12 DOES NOT: drop 0.4 V off a
high USB port. VIN2 now sees VBUS directly, against a 5.5 V
recommended maximum and a 6.0 V absolute maximum. A compliant source
is 4.75-5.25 V so this is 250 mV inside the recommendation and 750 mV
inside the rating, and U4 (the SRV05-4 on VBUS) clamps the transients
either way - but a non-compliant charger sitting at 5.6 V would now be
out of the recommended range where the Schottky used to hide it. Judged
acceptable: the same charger already puts 5.6 V on the SSR gate rail,
the WS2812B and the display, none of which had a diode in front of them
either.

+$3, the one feeder this change adds. Nothing fee-free does this job:
the Basic and Preferred libraries hold no power mux and no ideal-diode
controller at any voltage.


2026-10-26 (schematic review 2026-10-22, E4; fab-readiness C3): the
"24 V present?" sense is a divider on BUCK_5V, not the ST pin. ST
(pad 8, the south-west corner at rot 180) is the pin the paragraph
above deliberately parked: it is 0.3 mm from the USB pair on the south,
the 0.7 mm +5V escape from pad 7 runs along its row on the west, and
pad 1 (GND) faces it across the 1.48 mm column gap on the east. There
is no 0.15 mm track and no 0.6 mm via that clears 0.2 mm from all three,
so ST stays unconnected on this layout - a rev C item that goes with
re-laying the U12/USB corner. BUCK_5V answers the same question (the
buck is alive iff the 24 V input is up; U12's reverse-current blocking
keeps VBUS from back-feeding it), and R66 (100k) over R67+R68 (100k +
30k, both already on the BOM) puts 2.8 V on `PWR_STATUS` -> IO45 at
5.0 V, 2.7-3.0 V across the buck's tolerance, against the ESP32-S3's
2.475 V VIH. 22 uA. IO45 is a strapping pin, ignored on PSRAM modules
(eFuse-fixed VDD_SPI) - see `KILN_PIN_PWR_STATUS`'s help.

## C47 (design.py line 502)

U12's INPUT capacitors, one per channel, and the datasheet is the reason
rather than taste. TPS2116 SLVSFG1A s9: "using an input capacitance
(CIN) of 1 uF is sufficient"; s10.1: input capacitors "must be placed
close to the device". Until review A6 (2026-09-29) VBUS had no
capacitor anywhere on the board and BUCK_5V's nearest was C44, 85 mm
away at the buck.

What they are for is the switchover. With VOUT above 1 V a change of
channel is NOT soft-started (s7.3.2): the incoming channel closes onto
an output that sagged through the ~8 us break-before-make gap, and its
input has to supply that step at once. Behind a USB cable's ~1 uH, or
85 mm of BUCK_5V track, the pin sags with it unless the charge is
already at the pin - which is the reason s9 itself gives ("to prevent
the supply voltage from dipping when the switch is turned on"). The
outgoing channel's current has to go somewhere too, but it is opened
over microseconds, not cut: ~1 uH x 0.5 A/us is ~0.5 V at a pin rated
to 6 V, and the cap takes most of that as well. Both are bench events
(USB is only attached on the bench), and the bench checklist switches
the 24 V with USB attached on purpose.

0402s, the board's only ones, because nothing larger fits beside a
SOT-583. Since 2026-10-23 (PCB review 2026-10-05, item 6) both sit on
the pins themselves: C48 across the pocket between U12 pin 3 (VIN1) and
U1's courtyard, 0.7 mm of 0.25 mm track from the pad, and C47 in the
pocket west of pin 6 (VIN2), 0.5 mm from it, with the VBUS feed passing
over the top of its GND pad. Three nets had to give way, and each is
worth knowing before anything else moves here: the +5V link between
pins 2 and 7 is on B.Cu (pin 7 leaves west on F.Cu under C47 to the via
at (50, 36.5); pin 2 leaves east to its own via and comes back under the
part), the BUCK_5V trunk now loops round the north of U12 on B.Cu to
pin 5's via with C48's via sitting on that run, and AUX1 - which used to
cross under U12 on B.Cu at y 35.75 - now drops from U1 pin 9's via down
U1's west edge and runs diagonally beside LCD_CS. Both caps were tried
at the pins before (notes below) and failed on the auto-router's
plane-via placement; the 2026-10-23 layout is hand-routed, which is why
every via here is where it is. The earlier spots, for the record: C48
north of R63 against J1's courtyard (~5 mm of rail from pin 3), C47 at
J1's VBUS entry (~6 mm from pin 6).
C52923 is 25 V X5R, a Basic part (no feeder), and keeps roughly half
its capacitance at 5 V - the datasheet's 1 uF is a floor for the
typical case, not a tolerance, and ~0.5 uF is still what the pin
needs for a sub-amp step. A 6.3 V part would read
higher on paper and sit 1.1 V above a 5.25 V port at rated voltage.

## C41 (design.py line 568)

--- 24 V -> 5 V buck (the +5V rail) ---------------------------------
XL1509-5.0E1: 40 V abs max in, FIXED 5 V out, 2 A, 150 kHz, SOIC-8,
LCSC C61063 and a JLCPCB *Basic* part, so it costs no feeder fee. Two
things picked it over the adjustable 500 kHz parts: 40 V of input
headroom means the 12/24 V misconnect that used to destroy U2 is not
even a fault any more, and a fixed output needs no feedback divider -
two fewer parts and no divider to get wrong. FB (pin 3) ties straight
to the output for the fixed version. EN (pin 4) is active LOW, so it is
grounded to keep the regulator enabled.

The whole block sits in the south-east because that is the only region
of this board with room: 266 mm2 at x 100.25-119.25, y 95.75-109.75
carrying zero tracks and zero vias. The power corner cannot take it -
measured, its largest free pocket is 12.5 x 6.5 mm and the y 30-36 band
is boxed in by J2, R5 and U2 on three sides, so fitting the buck there
means exiling the LDO block out of the quadrant entirely.

Being 18-34 mm from the CT front-end is the price. It is affordable
rather than free: the ADE7953 measures a 50/60 Hz signal through the
1k/33nF filters on CTA_F/CTB_F, whose ~4.8 kHz corner puts 150 kHz
~30x down, and the MAX31856s are 50-60 mm away behind their own
filters. Keep the hot loop (C41/C42 -> U11 pin 1 -> pin 2 -> D7 -> GND)
tight; it, not the inductor, is what radiates.

--- INPUT CAPACITORS, BY THEIR VALUE AT 24 V (2026-10-28, PCB review
2026-10-05 item 3). C41/C42 were CL31A106KBHNNNE, 10 uF/50 V X5R in
1206, and Samsung's own DC-bias curve for that part gives -86.5% at
24 V: 1.35 uF each, 1.17 at 26.4 V, 1.03 at 29 V. The "20 uF" input bank
was 2.7 uF. They are now CL32B475KBUYNNE (C170099), 4.7 uF/50 V X7R in
1210, whose curve gives -33.9% at 24 V: 3.10 uF each, 2.91 at 26.4 V,
2.72 at 29 V - 6.2 uF for the pair where there was 2.7, from a smaller
nominal. The 1206 X7R 4.7 uF (CL31B475KBHNNNE) was the obvious cheaper
swap and holds only 2.24 uF at 24 V; the 1206 X7R 2.2 uF (Basic) holds
1.41. Thin dielectric, not the class marking, decides it. All four
curves were read from product.samsungsem.com, and the two that matter
are repeated in `datasheets/` by their LCSC sheets.

What the bank has to do, per the LM2596 datasheet this part copies: be
chosen for RMS current, not capacitance. At 1.0 A out and D = 0.24 the
input current is 0.43 A rms, 0.21 A per 1210 - nothing for an MLCC. The
ripple it leaves on VIN_P is I*D*(1-D)/(f*C) = 0.23 V pp at 127 kHz
(1%), and the pair's impedance at the switching frequency is 0.20 ohm.

NO electrolytic on the input, deliberately. The reviewers' "suitable
bulk capacitance" was considered: the HDR-15-24 sits on the same DIN
rail a few tens of centimetres away and is a stiff source, J2 is a
screw terminal nobody hot-plugs, D8 clamps any lead-inductance ring
at 33-37 V, and the input filter's Z0 (sqrt(0.5 uH / 6 uF) = 0.3 ohm)
is two orders under the converter's -Vin^2/P = -96 ohm negative input
impedance, so the Middlebrook margin is not in question. Against that,
a general-purpose 47 uF/50 V can has no ESR figure at 100 kHz in its
sheet, so its share of the 0.43 A cannot be bounded - at 0.3 ohm it
would take 40% and exceed its own 98 mA rating. A part that cannot be
qualified is not "suitable bulk".

--- THE LAYOUT (2026-10-28, same item). The block was rebuilt as the
review asked. U11 is turned 180 so its switch pin faces east, where D7
(horizontal, cathode west) and L1 (switch pad west) now sit: the switch
node is 9.4 mm of 0.8 mm F.Cu in two short legs from a 1.5 mm stub -
pin 2 to D7's cathode 3.9 mm, to L1's pad 4.5 mm - with NO via, where
it was 18 mm with two layer changes. Those tracks are LOCKED. C41 sits
2.5 mm south of pin 1 with C42 stacked under it, both GND pads on vias
beside them; D7's anode has two vias of its own, so the input loop
(C41 -> pin 1 -> pin 2 -> D7 -> plane -> C41) closes through the In1
plane 0.2 mm under the parts rather than round a 9 mm F.Cu detour. C44
stands on L1's output pad (3.1 mm), FB leaves pin 3 on a 0.3 mm trace
to a via and runs on B.Cu to C44's pad - the quiet node, away from the
switch node and the inductor, as the datasheet asks. VIN_P and BUCK_5V
cross the block on B.Cu, which was empty there. C46 (now a 6.3 mm can)
stays west of FID3, which moved 3.9 mm south to make room; the second
output ceramic is gone (see C44).

--- LOAD BUDGET (2026-10-28). The rail is rated for 1.0 A continuous at
50 C in-box ambient, and "~250 mA at 24 V" elsewhere in these notes is
that figure at 80% efficiency. Where it goes: the module's Wi-Fi TX
peaks (~0.5 A through U2), the display and its backlight (~0.15 A, on
+5V directly), LED1 (0.06 A), the buzzer (0.03 A) and the small
loads (~0.05 A) - about 0.8 A, leaving ~0.2 A for aux relays if SJ1
ties AUX_VP to +5V. At 1.0 A and 24 V, U11 dissipates ~0.6 W (1.2 V
saturation x 0.24 duty, 5 mA quiescent, ~0.18 W switching at 100 ns
edges) - +59 C at the datasheet's 100 C/W free-air figure, so Tj ~110 C
at 50 C ambient against a 125 C limit; the four GND pins into the pour
and plane buy some of that back, but the 1.0 A is a ceiling, not a
cruise. D7 carries 0.76 A average x 0.7 V = 0.53 W on an SMA with
plane vias; L1 0.23 W in its DCR. 2 A is the regulator's headline and
is not a rating of this board: at 2 A L1's peak current passes its
30%-drop point and U11 would be at 1.2 W.

## D7 (design.py line 606)

Catch diode. Non-synchronous buck, so this carries the inductor current
for ~79% of every cycle - it is not optional and it is not a snubber.
SS34 is already a BOM line and its 40 V / 3 A covers a 24 V input at
1.28 A peak. Pad 1 = cathode, on the switch node.

2026-10-27: SS36 (R+O, C7420367), 60 V, same SMA land. The catch diode
sees VIN_P in reverse during every on-time, and the F1 note's envelope
puts that rail at up to 38 V during a clamped fault - 2 V under the
SS34's rating, and over it on any excursion. The price is VF 0.70 V at
3 A against the SS34's 0.55 V: ~0.16 W more in the diode and ~1% of
buck efficiency at full load. The SS34 is retired from the BOM (D7 was
its only designator); its datasheet stays in datasheets/ as retired.

2026-10-28: placed with its cathode 3.9 mm from U11's switch pin on a
locked F.Cu track, its anode on two GND vias of its own, so the catch
current's return meets the input capacitors' return in the In1 plane
directly under the regulator (the layout note at C41). At the 1.0 A
budget it averages 0.76 A x 0.7 V = 0.53 W; the SS36's 3 A / 60 V
leaves the F1-envelope argument above unchanged.

## L1 (design.py line 613)

47 uH is the small end, not a lazy round number: at 150 kHz and
24 -> 5 V it gives dI = 5 x 0.792 / (47u x 150k) = 0.56 A, so 56%
ripple on a 1 A load and a 1.28 A peak. Going smaller makes that worse,
not the part - inductor volume goes as L x I^2.

2026-10-28, qualified at the load budget (1.0 A, see C41) with every
term at its worst datasheet bound rather than nominal: Fosc at its
127 kHz minimum, L at -20% (37.6 uH), Vin at the trim top (29 V) with
U11's 1.2 V saturation and D7's 0.7 V in the duty cycle. dI = 0.95 A pp
and the peak is 1.48 A at 1.0 A out (1.28 A at 0.8 A). FXL0650-470-M's
sheet (cjiang, in `datasheets/`) defines Isat MAX 2.08 A as the ~30%
inductance-drop point and Irms MAX 1.5 A as a 20 C rise from 25 C, so
the peak sits at 71% of the drop point and the 1.0 A rms at (1/1.5)^2 x
20 = 9 C of rise plus ~0.23 W of DCR loss - ~65 C at 50 C ambient
against the series' 125 C total. At the 2 A headline the same arithmetic
gives a 2.5 A peak, over the drop point: not a rating of this board.
The 68 uH the datasheet table lists for 20-40 V in (FXL0650-680-M,
Isat 2.0 A, DCR 320 mohm) would cut dI to 0.48 A at the cost of 0.1 W;
not taken, because at 1 A the 47 uH's margins above are comfortable and
the part is cached, placed and fitted.

L1 was 0.08 mm inside an 8 mm washer's footprint on H4 (PCB review
2026-10-05, item 8). On 2026-10-23 the buck's input caps (C41/C42/C43),
D7 and L1 all moved 1.5 mm north together - the caps up to the CT
terminal's courtyard, the VIN_P bus re-run below them at y 98.6 - and
L1's courtyard now clears the washer by 1.4 mm.

## C44 (design.py line 619)

2026-10-28: ONE 22 uF ceramic on the output, not two - C45 is gone (PCB
review 2026-10-05 item 3). The ceramic's job is the 150 kHz ripple,
and 13.65 uF (Samsung's curve for CL31A226KAHNNNE at 5 V: -38%) does
it: 0.061 ohm at the switching frequency, 36 mV pp of ripple at the
nominal 0.69 A inductor ripple, 41 mV at the worst-case 0.78 A. What a
second one would buy is harm: the ceramic shorts out C46's ESR zero
above f = 1/(2 pi ESR C_cer), which is 32 kHz with one part and 16 kHz
with two - and 16 kHz is where an LM2596-class loop is still working
(see C46 for why that zero is the whole point). The old note's "~32 uF
after bias" for the pair was wrong too: 27.3 uF, from the curve.

+5V on pin 1, SW_5V on pin 2, and the order is not arbitrary
even though an inductor is symmetric. A rail's port symbol is
never rotated - a +5V bar sits ABOVE its wire - so a rail on
the DOWNWARD pin makes power_path() elbow the wire sideways,
into the same flank field_pos() hands to an all-vertical-pin
part's Reference/Value. That collision is a check_sch_layout
failure, and swapping the pins is the whole fix.

## C46 (design.py line 634)

C46 is the reason this rail is stable, and it is NOT interchangeable
with more ceramic. The XL1509 is an LM2596-class VOLTAGE-mode regulator
with fixed internal compensation: the loop has an LC double pole and no
zero of its own, so it relies on the ESR zero of the output capacitor to
recover phase before crossover. The datasheet says so by omission and by
example - its 5 V/2 A design table (Rev 2.0 p.9) lists ONLY through-hole
electrolytic (180 uF/35 V) or surface-mount tantalum (100 uF/10 V) for
COUT, and p.8's note about "very low ESR output capacitors" offers a
feed-forward capacitor as the cure, which the FIXED-output part cannot
take: FB is tied straight to the output, so there is no divider to put
CFF across.

A ceramic-only output puts the double pole at 1/(2*pi*sqrt(47u*C)) with
an ESR zero near 1 MHz - i.e. nowhere useful - which is the classic
all-ceramic instability for this family. An electrolytic in parallel
plants the zero where the loop can use it. (The paragraphs below are
the 2026-10-28 re-derivation; the original argued the same topology
from a general-purpose part's assumed 0.5-1.5 ohm, which its datasheet
never said - the PCB review of 2026-10-05, item 3, was right about that.)

--- WHICH ELECTROLYTIC, AND WHY THE ESR HAS TO BE A NUMBER ON A SHEET.
The XL1509 is an LM2596 clone pin for pin (150 kHz, 1.23 V FB, 1.2 V
saturation, "internal compensation"), and neither sheet gives the error
amplifier, so the loop cannot be closed on paper. What the LM2596 sheet
DOES give is the documented capacitor class: "low impedance or low-ESR
electrolytic or solid tantalum capacitors designed for switching
regulator applications must be used ... the important parameters are
the 100-kHz ESR, the RMS ripple current rating, voltage rating, and
capacitance value", with the warning that an "extremely low" ESR goes
unstable, and tables of Nichicon PL / Panasonic HFQ / AVX TPS parts
whose 100 kHz ESR is 0.05-0.3 ohm at 100-330 uF - zeros at 5-16 kHz.
XL Semi's own 5 V / 40 V-in row is 68 uH with a 180 uF/35 V of that
class or an AVX TPS 100 uF/10 V. The RVT1C101M0505 fitted until now was
a general-purpose can: its sheet gives tan d <= 0.20 at 120 Hz (an ESR
of <= 2.65 ohm AT 120 Hz) and nothing at 100 kHz, which is not a
specification of the one parameter the regulator depends on.

C46 is now the Panasonic FK EEEFK1E101SP (C178540): 100 uF/25 V,
D6.3 x 5.8, and its sheet states impedance 0.36 ohm at 100 kHz, ripple
240 mA rms at 100 kHz, tan d 0.14, 2000 h at 105 C. ESR zero at
1/(2 pi 0.36 100u) = 4.4 kHz, in the documented band. 25 V where 7.5 V
would do (the LM2596 sheet's 1.5x) because, as that sheet also says,
the higher voltage rating is how the low ESR is bought. Panasonic is
one of the two electrolytic brands in TI's table; FK is its SMD
low-impedance line. The RVE1C101M0605 (0.85 ohm at 100 kHz, 6.3 x 5.4)
was the fallback if the 5.8 mm height had not fitted.

What the output network now looks like, computed as impedances (L 47 uH,
C_cer 13.65 uF, C_e 100 uF at 0.36 ohm): ESR zero 4.4 kHz; the ceramic
takes over above 32 kHz; LC corner 2.2 kHz; and the phase of the output
filter alone is -124 deg at 10 kHz, -129 at 20 kHz, -143 at 40 kHz. The
old network (27.3 uF of ceramic, 100 uF at an assumed 1 ohm) sat at
-148 / -163 / -172 at the same frequencies, and at the RVT's tan-d bound
of 2.65 ohm at -165 / -173 / -177 - i.e. for everything above ~5 kHz it
behaved as the all-ceramic case this part exists to avoid. The new
network recovers 25-45 degrees of phase across the band an LM2596-class
loop crosses over in. That is the whole of what can be said without the
error amplifier, and it is why the fitted part is now one from the
documented class rather than one argued into the role.

Ripple into it is fine: the inductor's 0.69-0.78 A pp is 0.20-0.23 A
rms, split by impedance 86% into the ceramic and 14% into C46 - 29-33 mA
against 240 mA. Output ripple 36-41 mV pp (0.7-0.8%).

STABILITY IS A BENCH ITEM AND IS WRITTEN AS ONE in
`docs/bench-smoke-test.md`: load step 0.2 -> 0.8 A, startup, no-load,
full load, cold and hot, with the subharmonic/ringing criteria that
decide whether the part is doing what this note claims. Until a board
has done that, this note describes the design intent and the margins
that can be computed, not a measured phase margin.

Fits where the D5 can was. The old note's "only free board here is 6.0
mm tall" was true of the previous layout; the 2026-10-28 re-layout
moved C44 onto L1's output pad and FID3 3.9 mm south, and the 7.1 mm
courtyard of the 6.3 mm can clears J7, FID3 and the board edge. No
fee-free equivalent exists: LCSC lists no aluminium electrolytic in the
Basic or Preferred libraries at all, so this line pays a feeder on
Economic ($3) and $0.15 for the part.

2026-10-27: it costs more than a feeder. Its JLCPCB part page reads
*PCBA Type: Standard Only*, so with U1 it is one of the two parts that
put the whole order on Standard PCBA, where every BOM line pays $1.53
and setup and stencil are three times Economic's (see
`gen_jlc.STANDARD_ONLY` and the README's 2026-10-27 correction). A D5
SMD electrolytic is a trivial hand-solder job, so if the order is ever
to be Economic, this is the easy half of it.

2026-10-29: the Panasonic FK that replaced it (C178540, above) reads
*PCBA Type: Standard and Economy* on its JLCPCB page, so C46 no longer
forces anything. U1 alone puts the order on Standard now, and the
Economic option is hand-fitting the module and nothing else.

## U1

2026-10-26, the module's thermal pad (pad 41, 3.9 mm). The KiCad
library footprint already carries a thermal-via pattern of its own:
nine 0.9 mm paste windows on 0.5 mm webs and TWELVE 0.3 mm thermal
holes as through-hole pads numbered 41, sitting on the webs, top open
inside the pad's mask and bottom tented (the pads carry no B.Mask).
(Espressif's own footprint has the nine surface pads and no holes; the
README's "Why KiCad's footprint" note is why this board uses KiCad's.) On top of that the
original generator drilled nine more GND vias, one in the centre of each
paste window - the ones the 2026-10-05 PCB review and JLC's DFM flagged.
Those nine are gone; the twelve library holes stay. The pad is the
unmodified library footprint again, and the four GND vias in the pour
just outside it ((66.0, 33.25), (71.0, 33.25), (67.75, 35.75),
(68.5, 35.75)) are unchanged. check_via_in_pad.py no longer exempts the
pad, so any via inside it fails pcb-check.

2026-10-27, sourcing: C3013945's JLCPCB part page reads *PCBA Type:
Standard Only*. It is the part that puts the order on Standard PCBA
rather than the Economic tier the README assumed (`gen_jlc.STANDARD_ONLY`;
C46 was the other until its 2026-10-28 replacement, which is Standard and
Economy). Going back to Economic means hand-fitting the
module - edge pads with an iron, centre thermal pad left dry - which is
routine but costs the thermal path the twelve web holes above exist for.
Not decided here.

## U2 (design.py line 672)

The regulator and the bulk-cap row east of it sit 1.5 mm further east
than they did, as one block: U2 36.6 -> 38.1, C1 44.0 -> 45.5, C3
49.2 -> 50.7, C4 53.8 -> 55.3. They are shoulder to shoulder (the
smallest pad-to-pad gap in the row is ~1.1 mm), so moving one means
moving all four, and the last of them still clears U12 and the module.

The reason is silk, which is a thin reason for moving a regulator and
was still the right call. J2 is the board's power INPUT, and the only
place its two screws can be named individually is the strip east of the
block - there is 0.67 mm to the board edge on the other side. U2's
three SOT-223 lead pads used to start 1.13 mm from J2's outline at
exactly the y of the `+` screw, leaving 0.93 mm of usable column for a
1.32 mm glyph, so `+` had nowhere legal to print and the placer buried
it inside J2 - the same failure the mark exists to prevent. No y offset
helps either: U2's leads span y 36.45..42.55 continuously and J2's two
screws are inside that band 5.08 mm apart. The column is now 2.43 mm.
TLV1117LV33, not AMS1117: same SOT-223, same 1117 pinout (GND/OUT/IN,
tab=OUT), but dropout is 700mV MAX at 1A against the AMS1117's 1.1V
at 800mA. The AMS1117 is a JLCPCB *Basic* part, so the swap keeps
getting proposed as a free $3 (#348). It is not free, and the reason
is NOT the 24V input:

U2's input rail has two sources. U11 is one, and behind the buck's
regulated 5.0V an AMS1117 would be fine. USB is the other, and it is
the one that decides the part: VBUS -> +5V is how the board runs on
USB alone, which is every bench and flashing session.

THIS SURVIVED U12, WHICH IS THE INTERESTING PART, because removing the
ORing diode's 0.4V is exactly the change that should have reopened it.
It does not, and the reason is that USB's own tolerance is wider than
the drop that was deleted. A 4.75V port (5V -5%) behind the old SS34
put +5V at 4.35V against the AMS1117's ~4.4V need - out of regulation
before the ESP32 had transmitted anything. Through U12's ~40 mOhm the
same port puts +5V at 4.73V, which looks like 330mV of margin and is
not: 4.75V is specified AT THE PORT, and a cable plus two contacts at
0.2-0.5 ohm take another 0.1-0.25V out of it at half an amp. That
leaves the AMS1117 somewhere between 0.2V and 0.05V, and behind a
bus-powered hub (4.35V at the connector, which USB permits) it is out
of regulation again. The TLV's 700mV-max dropout holds in all of it.
Neither U11 nor U12 raised the floor of the USB path - only the port
and the cable set that - so "the board has more headroom now" is true
twice over and still does not apply here.

Nor is the SOT-223 the constraint, which is the next thing asked. The
WHOLE fee-free library - 350 Basic plus 996 Preferred, enumerated, not
searched (2026-09-09) - holds three fixed 3.3V linear regulators in
any package: this AMS1117, a 100mA HT7533-1 (C14289, SOT-89-3) and a
200mA XC6206 (C5446, SOT-23-3L). Both of the others are an order of
magnitude short of the 240mA the ESP32 alone draws. There is no
fee-free 3.3V LDO on JLCPCB that can carry this rail, full stop.

The one thing that would work is a SWITCHER: XL1509-ADJE1 (C74192) is
Preferred, it is U11's own family, and a second one at 3.3V could reuse
L1's inductor and an SS34, so it adds no feeder fee and removes this
one. A real -$3. Three reasons it is not taken, and NONE of them is
"150 kHz is too noisy for the analog front end" - that objection was
made here once and it is wrong. The ADE7953 post-regulates internally
(VINTA/VINTD/REF are on-chip LDO/reference outputs, decoupled below),
the CT path corners at 4.8 kHz so 150 kHz is 31x out, and the MAX31856s
convert over ~100 ms behind a 50/60 Hz notch. The fundamental is filtered
three times over before it reaches anything that measures.

1. THE BEAT, which nothing filters. The XL1509 has no SYNC pin and its
own spread is 127-173 kHz, so two of them sit tens of kHz apart and
drift independently with temperature and load. Each is a duty-cycle-
modulated load on the shared rail, i.e. a mixer, and |f1-f2| lands
inside both control loops' bandwidth, so the loops track it and put
it on their outputs. That difference frequency goes anywhere from a
few Hz to 46 kHz and MOVES - down through 50/60 Hz where the ADE7953
integrates, and through DC where the MAX31856 lives. A 5 Hz beat is
temperature wander that never reproduces on the bench. Solvable by
frequency choice, never by filtering: see the rev-C note below.

2. FAULT ENERGY, and this is the kiln-specific one. R49's fail-safe
(below) has U10 - the watchdog that drops the SSR - sitting on the
rail U2 makes. An LDO pass element failing short puts 5V on that
rail. A 24V-fed buck failing short puts 24V on it. Same failure,
different energy, on the one part standing between a wedged
controller and 5 kW of element.

3. THE BOARD HAS NEVER BEEN BUILT. Putting a switcher on the analog
rail at the same time as first silicon on the metering and
thermocouple front ends means that if the noise floor disappoints
there is no known-good rail to A/B against. That is the actual
reason to wait, and it expires the moment rev B is characterised.

The one argument that DOES favour the switcher is thermal, and it is
better than the bench numbers suggest: 0.51 W at 300 mA is a ~27 C rise
in this SOT-223 with its pour, but a kiln controller's enclosure ambient
is not 25 C, and at 50 C ambient a 500 mA peak puts the junction near
95 C. Inside the 125 C spec, thinner than "0.85 W, that's nothing".

REV C, if U2's thermals turn out to be the real constraint: TPS5430DDAR
(C9864, Basic, 500 kHz, SOIC-8-EP) or TPS54331DR (C9865, Preferred,
570 kHz). Either beats U11 at ~350/420 kHz, out of band rather than
hoped away, takes 3.3V straight off the 24V input, and still reuses
L1's 47 uH (dI = 0.12 A at 500 kHz), so it stays fee-free. Design the
beat out; do not filter it.

Ceramic-stable at 0-ohm ESR (C3/C4 unchanged), Iq 100uA max. The old
trade — Vin abs max 6V against the AMS1117's 15V, so a 9/12V adapter
kills U2 first — is gone with the 5V input: J2 is 24V into U11 now,
and the only unregulated path to U2 is VBUS, which USB caps at 5.5V.
KiCad ships no TLV1117LV symbol; TLV1117-33 is the same family and
pin map, with the value carrying the real part.

2026-10-26: the tab's four +3V3 vias were inside the 2.0 x 3.8 mm tab
under 100 % paste (PCB review 2026-10-05 item 4). They now sit in the
masked U2_POUR 0.9 mm above and below the tab - (40.7, 37.0),
(41.8, 37.0), (40.4, 42.0), (41.3, 42.0); the lower pair is offset west
to keep 0.2 mm from the +5V trunk to C1 - so the tab's joint has no
hole under it and the vias are tented like any other. The thermal path
gained ~1 mm of 1 oz copper; U2 was already the part to measure on
board 1, and still is. check_via_in_pad.py no longer exempts the tab,
so a via wandering back into it fails pcb-check.

## C5 (design.py line 811)

Rotated (270, so GND is the SOUTH pad) rather than 0, so the GND pad
faces the open pour below instead of the sliver between C5, R1 and the
module's left edge. At rot 0 that sliver was too narrow to take a
stitching via once vias were barred from sitting inside pads
(router.VIA_PAD_GAP), stranding this pad on F.Cu.

This comment described a rotation the table had stopped carrying - the
`at` said 0 - and the board went back to failing the way the comment
says it does, just via a different mechanism: at rot 0 the pads lie
EAST-WEST, so EN enters on the west and has to come round the north of
the part to reach it, and the EN track then runs 1.30 mm over the GND
pad and starves its F.Cu thermal to one spoke where the rule wants two.
KiCad calls that `starved_thermal`, and it was the board's only DRC
violation after U12 went in (the mux re-rolled the routing order, which
is what moved EN onto that line). At 270 the pads lie NORTH-SOUTH: EN
is the north pad and meets its own track head-on, GND is the south pad
with the open pour under it. Do not "simplify" this back to 0.

## SW1 (design.py line 834)

SMD tactile switches, not the 6 mm THT part: XKB TS-1187A (LCSC
C318884) is a JLCPCB *Basic* part, so it carries no $3 feeder fee and
stays on the SMT line. The THT switches were one of five unique
Extended parts that existed only to force Standard assembly. (2026-10-27:
the order is on Standard anyway, forced by U1 and C46 - see
`gen_jlc.STANDARD_ONLY` - where a Basic line pays the same $1.53 feeder as
any other. The saving is real only once those two are hand-fitted.)

The two buttons are a PAIR and are now placed as one: RESET at x=91,
BOOT at x=100, both on y=25, in the free band between the module's east
edge (79.75) and H2's pad ring. RESET used to sit at (36.5, 24.2), on
the far side of the board from BOOT, which is the wrong arrangement for
the one operation that uses both - hold BOOT, tap RESET, release - and
it left each button in a 1.2-2.0 mm strip where neither legend fit
(`RESET` printed under its own button for two revisions; see
gen_pcb.SILK). Level with BOOT, the same 2.4 mm strip that takes `BOOT`
takes `RESET`, and the gap between them is 2.5 mm of clear board.

The cost is EN's length: the net's other members are R1/C5 beside the
module's west edge, so the switch stub is now ~40 mm rather than ~15.
That is acceptable here and would not be on a bare reset pin - C5 is a
1 uF sitting AT the module, so the stub is terminated in something very
stiff (10 ms with R1), and EN is a static level, not a signal. Do not
copy the arrangement to a design whose reset input has only a 100 nF.

## U4 (design.py line 884)

SRV05-4 rather than the USBLC6-2SC6 this used to be, which is the same
part D5 and D6 already carry. The driver was JLCPCB's feeder fee — one
part number across three designators instead of two costs $3 less per
order, and the SRV05-4 line chosen (C7420376) is a *Preferred* extended
part, so it is another $3 cheaper again. That is $6 of a $27 bill, and
it is the whole reason this changed. (2026-10-27: that $27 is the
Economic bill, and the order is on Standard because of U1 and C46 -
`gen_jlc.STANDARD_ONLY` - where this line pays $1.53 like every other.
The ESD and capacitance case below stands on its own.)

It is not a compromise made to save it. Measured off the two datasheets,
the SRV05-4 is the better part here on both axes that matter:

* ESD. USBLC6-2SC6 is IEC 61000-4-2 level 4 and no more - +-8 kV
contact, +-15 kV air. This one is +-30 kV on both.
* Capacitance. 1.0 pF per channel against the USBLC6's 3.5 pF max, on
a pair whose impedance the STACKUP comment goes to some length to
keep at 93.1 ohm.

Placed as a FLOW-THROUGH, and the pin map below is that decision. The
USBLC6 was a pass-through part: each channel is brought out on both
faces (1/6 and 3/4), so the pair entered one side and left the other.
The SRV05-4's four channels are independent, one pin each, and the
first rev of this swap used two of them (IO3/IO4, east face) and let
the pair reach them as stubs. That cannot be routed as a coupled pair
at all, and the reason is topological rather than a matter of skill:
both pads sit on ONE face, so whichever track runs nearer the part can
stub straight in, but the other has to cross it to reach its own pad.
The router did the only thing left - took D+ the long way round the
package - and the pair came out 50.8 mm against 33.2 mm, over 8 and 5
vias, with 0% of its length coupled.

So the part is turned 90 degrees to put its pad rows across the pair's
path (rot 270: pins 1/2/3 on the north row facing J1, 4/5/6 south), and
each line uses BOTH pins of one column: D+ enters pin 3, runs 1 mm under
the body, and leaves by pin 4 directly below it; D- does the same
through pins 1 and 6. Two straight lines, no stubs, no detour, and the
rest of the pair can be routed coupled from the south row onward
(gen_pcb.usb_pair_seeds draws this from the pad positions - move the
part and the copper follows). The price is the loading this comment
once refused to pay - 2.0 pF per line instead of 1.0 - and it is worth
paying now that it buys the flow-through: it is still under the 3.5 pF
the USBLC6 had, against a Full-Speed budget measured in tens of pF.

The middle column is VN (pin 2, GND) north and VP (pin 5, VBUS) south,
and that orientation is deliberate. Each middle pad is boxed in by the
two lines on either side of it, so each can only be reached through the
1.6 mm channel between them: pin 2 gets its plane via in the channel
between J1's escapes, and pin 5 gets VBUS by a via in the channel below
the south row, before the two lines converge into a pair. The hand
escapes in gen_pcb leave exactly those two slots open. VP goes to VBUS,
not +3V3: this array clamps to the rail on pin 5, and the lines it
protects are referenced to the 5 V bus.

SRV05-4: 1 IO1, 2 VN(GND), 3 IO2, 4 IO3, 5 VP(VBUS), 6 IO4 - the same
pinout D5/D6 are documented against below.

## U3 (design.py line 943)

--- Thermocouple ------------------------------------------------------
2x MAX31856 (TSSOP-14) replacing the rev A MAX31855. Pinout confirmed
against the KiCad 10 Sensor_Temperature:MAX31856 symbol and the Maxim
19-7534 Rev 0 datasheet (see hardware/kicad/datasheets/REV-B-NOTES.md
SS5): 1 AGND 2 BIAS 3 T- 4 T+ 5 AVDD 6 DNC 7 ~DRDY 8 DVDD 9 ~CS 10 SCK
11 SDO 12 SDI 13 ~FAULT 14 DGND. ~DRDY/~FAULT/DNC are left NC - both
status bits are readable from registers, and polling them is what keeps
the GPIO budget closing (spec 4.1). AVDD/DVDD are separate pins but must
share one 3V3 rail (datasheet: AVDD-DVDD limited to +-100mV) with
independent 100nF decoupling per pin, each to this board's single GND
net (no AGND/DGND split plane exists elsewhere on this board).

REV-B-NOTES.md SS5a overrides the brief here: there is NO bias bypass
capacitor. "This pin is floating when no conversions are taking place...
No bypass or decoupling is specified" (datasheet p.10), unlike AVDD/DVDD
which both explicitly call for one. The 0.01uF cap in the datasheet's own
application drawings belongs to the T- common-mode filter, not to BIAS.
The brief's C14 (100nF, BIAS->GND) is therefore omitted outright.

BIAS routing: Figure 8 (the filtered topology this design follows, with
the 100R series resistors) is explicit that "BIAS connects to the
thermocouple side of the resistor" (SS5a) - i.e. the RAW terminal-side
node, upstream of the series R, NOT the IC-side filtered T- pin. That is
a different diagram from the datasheet's simple Typical Application
Circuit (no series resistors), where BIAS and T- share one pin-level
node - do not conflate the two. So here BIAS (pin 2) joins TC1_N/TC2_N
(the raw terminal net, same node as J3.2/R15.1), while T- (pin 3) stays
alone on the IC-side filtered node TC1_N_F/TC2_N_F, symmetric with
T+'s TC1_P_F/TC2_P_F. The open-thermocouple detection bias current
sources from BIAS through the thermocouple itself, not through the
external filter resistor - routing it through R15/R17 the way the
simple-circuit reading would have put that bias current across the
filter resistor, which Figure 8's topology specifically avoids.

Input filter per REV-B-NOTES.md SS5c / datasheet Figure 8 ("Typical
Connection to Reduce the Effect of Noise Pickup"), fit unconditionally -
this board sits beside SSR-switched mains wiring with a Wi-Fi radio on
the same PCB, the RF-field case the datasheet calls out: 100R 1% series
in each leg (1% so the T+/T- series resistors stay matched - datasheet
p.28 ties resistor mismatch directly to offset voltage), then, on the
IC side of those resistors, 100nF differential across T+/T- plus 10nF
common-mode from each leg to GND. No TVS on these nets (spec 4.1): a TVS
array's leakage into a ~40uV/degC source is an accuracy error, not
protection - the RC filter plus the chip's own input clamps are it.

TC1_N/TC2_N run to the screw terminal raw, NOT to GND - unlike rev A's
MAX31855 whose T- was grounded at the chip, each MAX31856 channel keeps
its own floating differential pair (T- is only soft-referenced near
AGND through the internal ~2k BIAS network, not hard-tied to it).
Ungrounded-junction probes are required on the finished board: both
channels reference T- through that shared internal biasing, so two
grounded-junction probes in one kiln chamber would form a ground loop
through the kiln body (documentation obligation, Task 16 - not a board
change).

TC1_CS follows the copper: it sits on U1 pin 39, high on the module's
east side facing U3, and runs to ~CS (pin 9) and on to its pull-up R50
through 3 vias. It used to keep rev A's TC_CS pad through the rename -
pin 18, on the module's bottom edge - which sent it back up under U1 on
B.Cu while IN3 left pin 39 the other way for its filter block at the
bottom left. The two crossed and each ran the long way round; swapping
the pins took the pair from 197 mm / 11 vias to 167 mm / 5. It is just
a GPIO to firmware, so the cost was a Kconfig default. IN3 keeps an
ADC1-capable GPIO on pin 18 (see R12).

## C13 (design.py line 1006)

AVDD/DVDD decoupling. The datasheet requirement is "independent 100nF
per pin", which this satisfies; the DISTANCES are loose and deliberately
left that way. Measured pad-to-supply-pin, both channels: 6.4 mm to
AVDD, 5.1 mm to DVDD.

They agree because THE TWO CHANNELS ARE NOW THE SAME CIRCUIT, laid out
twice at a 12.0 mm pitch, and that is the point of the arrangement
rather than a coincidence worth preserving by hand. Every part below
sits at a fixed offset from its own MAX31856 (see TC_CHANNEL_DY), so a
change to one channel is a change to both and the two thermocouple
front-ends cannot silently diverge - which they had. U5 used to be
rotated 90 against U3's 270, a 180 deg flip that put its AVDD/DVDD on
the opposite rows from U3's while the caps stayed on a shared x=90
column derived for U3: 9.0 mm and 7.7 mm, the worst pair on the board,
and nothing said so. Worse, the flip put U5's ANALOG row (pins 1-7,
TC2_N/TC2_N_F/TC2_P_F) on the south side while its 100R/100nF/10nF
input filter sat to the north, level with the digital row - so the two
channels' input networks were not the same shape, on a differential
input worth ~40 uV/C. See the note above U5.

Tightening the caps FURTHER was tried and REVERTED; do not repeat it
without reading what happened. Parking each cap on its own supply pin's
centreline at 1.74 mm left four nets unroutable (TC1_CS, TC2_CS,
TC1_P_F, TC2_P_F), because two things already own those centrelines out
to ~2.75 mm: the pre-seeded fanout escapes (FANOUT["U3"] = 1.5 mm plus
the alternating 0.75 mm, whose far ends ARE the router's terminals) and
the +3V3 pins' own plane vias, which land at FANOUT + 1.25 on the same
ray. A 0.65 mm pitch TSSOP has no lane to spare either side. Trading a
routing perturbation in the densest region of the board (2.30
parts/cm2) for a good-practice distance, on a ~100 SPS sigma-delta with
no fast edges, is not a trade worth making.

## U5 (design.py line 1062)

--- Thermocouple channel 2 (load TC) - channel 1 again, 12 mm south
and MIRRORED, with TC2_* nets and TC2_CS. Every `at` below is the
channel-1 line with TC1_Y -> TC2_Y and the offset flipped by TC2_DY,
so the filter, the caps and the terminal all follow the chip's flip
instead of being left on channel 1's side of it (see the TC1_Y/TC2_Y
note above - they had been, and channel 2's differential inputs paid
for it). Move a part in one channel and move it in both.

THE MIRROR IS IN X AS WELL AS Y, and only the y half used to be applied.
Flipping U5 reverses the order of its analog pins: U3 reads P_F (97.00),
N_F (97.65), N (98.30) west to east and U5 reads N (95.70), N_F (96.35),
P_F (97.00). The chip did not move in x, so the FILTER COLUMNS have to
reverse to follow it - R16 (the P leg) east at 105.9 and R17 (the N leg)
west at 102.2, the opposite of channel 1's R14/R15. With channel 1's x
order copied straight across, both ends of the channel crossed: J8's
near screw (P, y 53.0) reached for the far west resistor while the far
screw (N, y 47.92) reached for the near east one, and downstream P_F
left the west pad for the east pin while N_F did the reverse. Channel 1
routes 35.2 mm over ZERO vias; channel 2 was routing 128.9 mm over ten,
for the same circuit, on a differential input where 40 uV is a degree.

C20 turns with them (rot 180), which puts its N_F pad exactly under
R17's. C21 and C22 do not move and both get closer to their own nets as
a side effect - C21's P_F pad now lands on R16's, where before it was
3.7 mm away across the pair.

R16/R17 and C20/C21 keep one exception to the y mirror, and it is J8
rather than U5 that makes them one: they are pushed 1.6 mm and 0.4 mm
FURTHER out than the mirror asks. Channel 1's filter row clears J3's screws by 0.47 mm going
north; mirrored, channel 2's would land on J8's - R17's pads span y
52.9..54.3 and J8's `K+` legend wants 52.25..53.75, the same board.
There is no second column to move the legend into (J8's body starts
1.16 mm east of R17's pads), so the resistors give way. What matters -
the filter on the same side of the package as the analog pins it
filters - is unaffected. ---

## Q5 (design.py line 1131)

--- SSR output: two opto-driven 24 V channels -------------------------
REV B.2. The terminals were "+5 V, watchdog-gated, switched low side"
with the GPIO on the channel MOSFET's gate through 100R. They are now
"24 V, always live, switched low side", the gate is driven through an
optocoupler, and the watchdog sits in the shared return instead of the
supply. Three separate decisions, so three separate derivations.

--- WHY 24 V ---------------------------------------------------------
The board's input became 24 V when U11 arrived, so a 5 V control output
on a 24 V board was the last place the old input voltage survived. An
SSR-40DA-class input takes 3-32 V, so both work; 24 V is chosen for the
noise margin on a loom that runs beside element wiring, and because it
is what every other DC control terminal in a kiln cabinet already is.

The high side is VIN_P - post-F1, post-D8, post-Q8 - not VIN. That is
the whole point of picking a node: a terminal fed from raw VIN bypasses
the reverse-polarity switch and the fuse, and a screw terminal is
exactly where a wiring mistake lands. This used to cost ~0.4 V, the
drop of the SS34 that Q8 replaced; it now costs ~33 mV, so the terminal
really is at the input voltage and the 3-32 V SSR window is entered
with the whole of it.

CURRENT BUDGET, and it is a real limit rather than a note. F1 holds at
750 mA and U11 draws ~250 mA of it, so the two channels share ~400 mA
before the fuse starts to think about it. Two SSR inputs (~15 mA each)
and two indicators (~5 mA each) is 40 mA, a 10x margin. A small DC
contactor coil per channel fits; two large ones do not. D9/D10 are
sized to that budget and no further - see them.

--- WHY THE OPTOCOUPLERS ARE BACK, AND WHAT THEY ARE FOR --------------
Rev B opto-isolated both channels (U8/U9 + SJ3/SJ4) and then REVERTED
it, because an optocoupler only isolates if the SSR control loop is
powered from a supply that is not this board, and this board powers it.
THAT REASONING IS STILL CORRECT AND IS NOT BEING OVERTURNED. These
terminals are still board-powered, the two sides still share GND, and
nothing here is an isolation barrier. There is no pour keepout, no
router keepout, no rule area and no check_isolation.py, and none of
those should come back - re-read the revert commit (93a31d7) before
adding one.

What changed is the failure the parts are bought for. At 5 V, a channel
MOSFET failing gate-to-drain put 5 V through 100R into a GPIO, which
the ESP32's clamp survives. At 24 V the same single failure puts 240 mA
into that clamp and takes the module with it. The opto removes the
path: the only thing the MCU touches is an LED, so no single failure in
the 24 V domain has a conductor to the GPIO at all. That is
CONTAINMENT, not isolation, and the distinction is the reason the
keepouts stay gone.

It is also not more parts than the alternative. A zener from gate to
GND contains the same fault for the same one part per channel, and it
contains it by conducting - a part that has to survive the fault to
work, and that fails open silently. The opto contains it by not being
a conductor. Same count, stronger mechanism.

Per channel: SSRn_CTRL -> 220R -> U8 LED -> GND.

220R is sized against the ESP32's GUARANTEED V_OH, 0.8*VDD = 2.64 V,
not against 3.3 V, and that is the whole reason it is not 330R: the
CTR bin is only specified at I_F = 5 mA and CTR falls off steeply
below it, and 330R at the guaranteed corner gives 4.7 mA - under the
floor, on the datasheet figure this board is supposed to use.
I_F = (V_OH - V_F)/220: 9.5 mA at 3.3 V / 1.2 V, 6.5 mA at the
guaranteed 2.64 V, and 5.6 mA at 2.64 V with V_F at its 1.4 V max
(TLP291 datasheet: 1.1/1.25/1.4 V at I_F = 10 mA, so the max at
~6 mA is lower still - 5.6 mA is the pessimistic bound).
Worst case is still over the floor, and the 9.5 mA best case is half
the ESP32's 20 mA recommended source current and a fifth of the LED's
50 mA rating.

The GB rank (datasheet p.2: CTR 100-400% at I_F = 5 mA, V_CE = 5 V -
100-400, not the 100-600 the LCSC listing claims) then gives
I_C >= 5.6 mA (the worst-case I_F at CTR 100%) against the 1.0 mA the
gate node needs through R7's 4.7k: 5.6x. That margin is also the aging
budget - an LED driven this far inside its rating loses CTR slowly.

THE OPTO PULLS THE GATE DOWN, AND THE ZENER SETS HOW FAR (rev B.4).
U8's transistor sits emitter-to-GND, collector into the gate node
through R69 (10k). The gate node is referenced to the P-FET's SOURCE,
which is SSR_24V, so what matters is V_SG = V_rail - V_gate, and that
is clamped by D13 (BZT52C8V2, gate to source) to 8.2 V as soon as the
current through R69 exceeds what R7 (10k, gate to source) takes at
8.2 V, i.e. 0.82 mA - true for any rail above ~17 V, which is the
whole 21.6-29 V trim range and the 38 V clamped fault alike. The gate
voltage therefore comes from a ZENER, not from the opto's CTR, which is
the same "from a rail, not a ratio" rule B.2 bought with the 5 V
collector supply; 8.2 V is comfortably past the LP2309LT1G's 4.5 V
R_DS(on) spec point (260 mOhm max there, ~220 mOhm at 8 V) and inside
its +-20 V V_GS. Without the zener the R69/R7 divider alone would put
(V - 0.3)/2 across the gate: 11.9 V at 24 V, 18.8 V at the 38 V fault
and 24 V on the 48 V transient - which is why the zener is there.

Opto current I_C = (V_rail - 8.2 - V_CE(sat))/10k: 1.3 mA at 21.6 V,
1.55 mA at 24 V, 2.05 mA at 29 V, 2.95 mA while D8 clamps a fault at
38 V. Against the >= 5.6 mA the GB-rank TLP291 passes at the worst-case
LED current (CTR >= 100 % at I_F >= 5.6 mA, see above) that is 3.6x at
nominal, 2.7x at the trim top and 1.9x in the fault, and the margin is
still the aging budget. The zener carries I_C - 0.82 mA, 0.5-2.1 mA:
below its 5 mA spec point, so V_SG sits nearer 7.5-7.8 V than 8.2 V,
which changes nothing above. V_CEO is 80 V against a collector that
sees at most the rail.

R7/R20 (10k since B.4, gate to SOURCE) hold the P-FET off against the
opto's dark current. The datasheet bounds I_CEO at 0.08 uA max at 25 C
and 50 uA max at 85 C (at V_CE = 48 V; this collector sees ~24 V), so
the 85 C corner is 50 uA x 10k = 0.5 V of V_SG against the LP2309LT1G's
1 V minimum |V_GS(th)|: 2x, the same margin review A5 (2026-09-29) set
for the 4.7k/CJ2310 pair this replaces. 4.7k would double it but would
also need 1.74 mA at 8.2 V, more than R69 delivers at the trim bottom,
and the zener would stop clamping. The GPIO still cannot reach the
gate at all.

--- REV B.4 (2026-10-28): HIGH SIDE, GROUND-REFERENCED ----------------
B.2 put the switch in each channel's RETURN (pin 1 always-live VIN_P,
pin 2 switched low side, CJ2310s) and the watchdog's Q7 in the shared
return. The 2026-10-05 schematic review (item 3, fab review A1) named
the hole: an SSR's - lead that finds ground by any route - chafed onto
the earthed backplate, landed on the PSU -, commoned with the other
channel - turns that SSR on with nothing on the board able to turn it
off, because the fault bypasses the channel switch AND Q7. B.1 could at
least drop the terminal rail; B.2 could not. Item 11 was the second
cost of that topology: Q5 failed short with the window expired pulled
SSR_RTN to 23.7 V through the SSR's own input and put -23.7 V on the
healthy channel's gate.

B.2 rejected a high-side arrangement for one reason, written below the
old derivation: no fee-free 60 V P-channel part at JLCPCB. That premise
died with the Economic tier (2026-10-27: U1 is Standard-only, so every
line pays the same $1.53), and the LP2309LT1G (LRC, C383253,
60 V, 1.9 A, +-20 V gate, SOT-23, "Economic and Standard") is exactly
the part the objection said did not exist.

THE TOPOLOGY. Each terminal's + (pin 1, still where the SSR's + goes)
is SSRn_OUT, the drain of a P-channel Q5/Q6 whose source is SSR_24V;
the - (pin 2) is board GND. SSR_24V is VIN_P through Q9, a third
LP2309LT1G that is the watchdog's cutoff: Q7 (the CJ2310, gate on
SSR_EN) pulls Q9's gate down through R71 (10k), D12 clamps Q9's V_SG to
8.2 V and R22 (100k, gate to source) holds Q9 off whenever Q7 is not
pulling. Same gate network three times, same part three times.

WHAT IT BUYS. (a) A - lead on ground is now the wiring diagram, not a
fault. (b) A + lead that finds the chassis is a short through the on
channel's Q5 and Q9 to ground: the HDR-15-24 goes constant-current at
110-145 % (0.7-0.9 A) and hiccups, or a bigger PSU trips F1 at 1.5 A;
the LP2309LT1G is rated 1.9 A continuous / 7.6 A pulsed and the SSR,
with 0 V across it, is OFF. Either way the fault fails safe and
announces itself (the board reboots or the fuse holds). (c) Q5 failed
short: the channel is on regardless of firmware, the over-temperature
trip blocks the kick (safety.c, s_wdt_blocked), the window expires and
Q9 opens - B.1's coverage, back. (d) Item 11 is gone: with Q9 open
nothing pulls SSR_24V, and Q5/Q6's gates ride their sources through
R7/R20, so a failed channel cannot stress the healthy one. (e) Q9
failed short is the one new exposure, and it is exactly B.1's Q4
failed short: the watchdog loses its load-path switch, the channels
stay under firmware control through the optos, and the bench sees it
as SSR_24V live with SSR_EN dead.

WHAT IT COSTS. B.2 had two independent things collapse when the
window expired (opto collector rail AND Q7's gate); B.4 has one load-
path effect, Q9. The second mechanism now is the firmware's own e-stop
driving the GPIOs off, which does not depend on SSR_EN at all. Also
one more BOM line (C383253, 50 lines, $110.27 fixed on Standard) and
seven more placements; D12-D14 are D11's zener, R69-R71 and the new
R7/R20 are the 10k line.

THE SHARED CUTOFF, NUMBERS. Q7 on: I = (V_rail - 8.2)/10k - the 82 uA
R22 takes = 1.5 mA at 24 V, 2.0 mA at 29 V, 2.9 mA at 38 V into D12;
Q7's gate is SSR_EN at ~5 V, where the CJ2310's 125 mOhm is specified,
so its drop is nothing at 3 mA. Q7 off: its I_DSS (1 uA max at 60 V)
across R22 is 0.1 V, and Q9's gate sits on its source. Q7's drain
stands off the rail (24-38 V, 48 V transient) against 60 V; Q9 and
Q5/Q6 stand off the same rail drain-to-source when off, against -60 V.
Nothing needs an R22-style pulldown on SSR_24V: with Q9 off the node
floats, but Q5/Q6 are off by V_SG = 0 whatever it floats to, and the
terminal's own load (an SSR input, ~1.2k) defines OUT at the 10 uA of
I_DSS a channel can leak.

DISSIPATION. R69/R70/R71 (10k, 0805, 125 mW): (V - 8.5)^2/10k =
24 mW at 24 V, 42 mW at 29 V, 87 mW during a clamped 38 V fault. R7/R20
and R22: 6.7 mW and 0.7 mW. D12-D14 (200 mW): 8.2 V x (I - I_R) =
6-12 mW nominal, 17-24 mW in the fault. Q5/Q6 at the 200 mA coil
budget: 0.22 Ohm x 0.04 = 9 mW; Q9 at the 400 mA channel budget: 35 mW,
0.1 V - the terminal still sees the input within 0.15 V.

THE OLD DERIVATION (B.2, for the record) argued that Q7 in the return
was not the rejected "stacked low side" because its gate came from a
5 V rail where the CJ2310 is specified; that argument was sound and is
why Q7 survives as the level shift. R22's 100k was sized so that, with
Q5 failed short and the window expired, R22 in series with the SSR's
input passed 237 uA rather than 10k's 2.1 mA (an SSR-40DA input can
trigger from ~2 mA); that role is gone, and 100k is kept as Q9's
gate-to-source pull-off because its only job now is to beat Q7's 1 uA
of I_DSS.

--- PARTS -------------------------------------------------------------
LP2309LT1G (LRC, C383253, SOT-23 G-S-D, the same pinout as the
AO3401A and the CJ2310): -60 V V_DS, +-20 V V_GS, -1.9 A, 215 mOhm max
at -10 V and 260 mOhm max at -4.5 V, V_GS(th) -1 to -3 V. The AO3401A
Q4/Q8 use is a 30 V part and would sit outside its rating for the
whole of the clamped fault, so it is not an option here any more than
the AO3400A was for the CJ2310s. CJ2309A (C7433254) and PJM2309PSA
(C411721) are the same device from other houses and were out of stock
on 2026-10-28; the LRC part had 165,000. Extended, "Economic and
Standard", $0.078 at 5. The CJ2310 stays on the BOM for Q7 alone.
D12-D14 are D11's BZT52C8V2S (Basic); R69-R71 and R7/R20 are the 10k
line (C17414, Basic), so the 4.7k line keeps only R44/R45.

## U8 (design.py line 1312)

SOP-4, not the SMDIP-4 this started as, and the reason is geometry
rather than electricals. The SMD-DIP4 body is 12.04 mm wide over its
courtyard; the corridor between J4/J9 and the rest of the block is
~5.5 mm and has to carry BOTH these parts and the four per-terminal
legends (`24V`/`OUT` at each screw's y, which silk.py may slide in x
but not in y). A 12 mm opto leaves the legends nowhere to go and they
print on the terminal body - three check_silk failures, and no amount
of re-spacing fixes it because the corridor is simply too narrow.
8.50 x 3.10 mm opens it to ~6.7 mm and everything else falls out.
Costs one Extended feeder; the LTV-817S was Basic.

## D9 (design.py line 1334)

Freewheel across the terminal pair, cathode on the supply. An SSR input
is resistive and needs none; a DC contactor coil - the load 24 V is
worth having for - needs one or it puts its collapse across Q5. Sized
to the F1 budget above and not beyond it: the 1N4148W's 450 mA
repetitive peak covers a coil interrupted at the ~200 mA per channel
that budget allows, and it is already on the BOM (D3/D4).


2026-10-26 (PCB review 2026-10-05, item 12): D9/D10 are B5819W now
(JSCJ, C8598, Basic), a 1 A / 40 V Schottky in the SAME SOD-123
footprint, not the 1N4148W. The ordered 1N4148W (Semtech, C81598) is
rated 150 mA average with 0.5 A/1 s non-repetitive surge; the "450 mA
repetitive peak" the paragraph above leaned on is not in its datasheet,
so a 200 mA contactor coil chopped at the SSR timer's rate was never
qualified. The B5819W is 1 A average, 9 A surge, 0.6 V at 1 A. The SS34
(D7's part, 3 A) was the first choice and was tried: its SMA land is
5.6 mm long and the x = 36.3 column (R22, D9, Q5, Q7, D10, Q6) is on a
4.4 mm pitch, so it overlapped three courtyards and two vias per diode.
1 A is 5x the coil budget; the footprint swap would have been a
re-layout of the whole SSR column for nothing. Reverse voltage is 40 V
against 24 V nominal and the 30 V TVS clamp; the 48 V clamp transient
(review item 1) is a separate, still-open coordination item that this
does not change.

2026-10-27, one day later: 1N4007W (FUXINSEMI C3018540, the SOD-123
body - not the -FL), 1 kV / 1 A average / 25 A surge, same land, drawn
with Device:D rather than the Schottky symbol. The paragraph above
undersold the reverse requirement. With its channel ON the freewheel
diode stands off the whole rail: 24 V nominal, 29 V at the HDR-15-24's
trim top, and ~38 V while D8 clamps a fault (the envelope at F1), so
the B5819W's 40 V had 2 V of margin on a sustained fault and none on a
transient. A standard-recovery rectifier is the right part for a
contactor coil freewheel - the coil is switched at the SSR timer's
rate, where microseconds of recovery do not matter - and 1 A average
still covers the 200 mA coil budget five times over. VF 1.1 V at 1 A
makes the coil current decay a little faster than through a Schottky,
which is harmless here.

2026-10-28, rev B.4: the freewheel now sits across the terminal the
other way up, cathode on SSRn_OUT (the switched +) and anode on GND,
because the - pin is ground now. Same part, same land, same job: a coil
between + and - still has its diode across it. Standing off the rail
with the channel on is unchanged at up to 38 V against 1 kV.

## LED3 (design.py line 1343)

The channel's readout row: the indicator resistor, the LED and the
control test point on one y, with channel 2's row the same three parts
8 mm south on the same three x. See SSR_IND_Y / SSR_TP_X.

10k, not the 680R this was at 5 V nor the 4.7k it was at first on 24 V:
(24 - 2.0)/10k = 2.2 mA and 48 mW. At 4.7k the resistor burned 103 mW,
82% of an 0805's 125 mW, and 127 mW - over rating - at the HDR-15-24's
+10% trim (26.4 V); at 10k that corner is 60 mW, and 73 mW at the trim
range's real top of 29 V (2026-10-27). An indicator LED is
plainly visible at 2 mA. Review A3, 2026-09-29. The pair
still sits across the TERMINAL, so it reads the channel's actual
output state - lit only when Q5 AND Q9 are both conducting, which is
firmware asking and the watchdog agreeing. (Rev B.4: anode on SSRn_OUT
through R10/R21, cathode on GND - the pair moved to the other side of
the terminal with the switch, and the numbers above are unchanged.)

## Q7 (design.py line 1392)

--- The watchdog's level shift (rev B.4) -----------------------------
Q7 used to be the switch in the shared return; since B.4 it is the
N-channel that pulls the 24 V cutoff Q9's gate down through R71 when
SSR_EN is up (see the SSR block). Its drain stands off the rail through
R71 whenever SSR_EN is down, so it is still the 60 V CJ2310, and it is
the only place that part remains. Gate on SSR_EN at ~5 V, where the
125 mOhm is specified, so its drop at 3 mA is nothing.

## R22 (design.py line 1402)

Rev B.4: gate-to-source pull-off of Q9, 100k, so that with Q7 off
nothing but Q7's 1 uA of I_DSS (0.1 V) acts on the gate and Q9 is off.
The B.2 sizing argument (237 uA through a failed-short channel into
the SSR) is history; see the SSR block.

Placed north of D9 rather than in the channel-2 column with the parts
it serves, and that is a SILK constraint, not an electrical one. A
pulldown does not care about a 9 mm stub, and the column between Q7 and
the display-damping row is the overflow area the silk placer was using
for R54/R56's reference designators - those two are boxed between the
R55/R58 row and J5 and have nowhere else to go. Four parts in that
column cost two silk_overlap violations against a budget of zero; three
parts and one fewer designator clears it.

## R49 (design.py line 1413)

--- Hardware watchdog (Task 12) ---------------------------------------
WDT_KICK (U1.29, a firmware square wave) retriggers U10, a one-shot
whose Q output keeps Q3 enhanced, Q3 holds SSR_PG (the gate of the
high-side switch Q4) down, and Q4 supplies SSR_EN - the +5V rail that
enhances Q7, which pulls the gate of the 24 V cutoff Q9 down so that
SSR_24V, both channels' source rail, is live (rev B.4; in B.2/B.3
SSR_EN fed the opto collectors and Q7 switched the shared return). Stop
kicking and the window (1.3-3.1s worst case, R46*(C38+C49), see
arithmetic below) expires, Q falls, R47 pulls SSR_PG to +5V, Q4 turns
off, R18 pulls SSR_EN down, Q7 lets go, R22 pulls Q9's gate to its
source and SSR_24V is dead - both terminals are off whatever the
channel switches are doing. This is the only interlock on this board that survives
firmware death - lid/over-temp/stale-TC are firmware-owned and die
with it. It is still only SUPPLEMENTARY: the real protection is a
mechanical over-temperature cutout in series with the element
contactor.

THE RETRIGGER IS EDGE-DRIVEN - that is the entire point. Firmware
wedged with WDT_KICK stuck high must fail exactly like firmware that
stopped toggling, and a monostable retriggered on B's RISING edge does
precisely that: a DC level delivers no edge, the window expires, Q falls.

Gates ONLY the heat outputs (SSR_EN). AUX1-3 (vent/purge/spare, via
U6/ULN2003) and the buzzer are on separate nets entirely - untouched by
Q3/Q4 - so a stalled controller can still open its vent.

--- WHY NOT THE DIODE CHARGE PUMP THIS REPLACES ----------------------
Rev B shipped a BAT54S clamp-and-peak-detector (C38 100nF, C39 1uF,
R46 1M) into Q3's gate, and it does not work. Solving its steady state
exactly - V_hold(min) = d*a*A/(1-b*d), a = C38/(C38+C39), d = e^(-T/tau),
A = V_OH - 2*Vf - gives, at the 5 Hz kick the firmware plan called for,
0.63V against the AO3400A's Vgs(th) max of 1.45V. The rail never comes
up. It is not a corner case either: the typical corner (V_OH 3.3V,
Vf 0.2V) reaches 0.84V, below even the TYPICAL 1.0V threshold.

The sizing note this replaces computed the DECAY constant (R46*C39 = 1s)
and the gate margin but never the REPLENISHMENT constant
(R46*C38 = 0.1s), and flagged its own values as an unverified assumption
because "no target kick frequency or hold-decay spec exists yet".

Raising the kick rate rescues the gate voltage (>= 250 Hz) but cannot
rescue the temperature behaviour. Schottky reverse leakage through the
BAT54S's second diode (nothing to do with the board's old D2, which was
the USB ORing part U12 replaced) discharges the hold node in parallel
with R46 and roughly doubles per
10 C, so the budget for a transient firmware stall - a flash erase
stalls BOTH cores - falls from 0.31s at 25C to 0.11s at 60C, and near
85C the pump stops holding at all. A kiln controller sits next to a
5 kW heat source. No choice of passives fixes that, because the leak is
in the timing path; the fix is to take it out of the timing path.

--- THE ONE-SHOT ----------------------------------------------------
U10 (SN74LVC1G123, LCSC C26159250) is a single retriggerable monostable.
WDT_KICK drives B (rising-edge trigger) with A tied low and CLR high;
every edge restarts the window, and Q stays HIGH for as long as edges
keep arriving. Q drives Q3's gate directly. Q3, Q4, R47 and the SJ2
defeat jumper are unchanged - only what holds Q3's gate up has changed.

Window: tw ~= K*R*C with K = 1.0-1.1, the datasheet's own spec'd bound
at its 10k x 0.1uF anchor, and the same limits at 125C as at 85C.
R46 1M 1% and C38 || C49, two 1uF 50V X7R 0805 (rev B.3, schematic
review E5 - the 22uF X5R 1206 they replace is unspecified above 85C,
loses capacitance to DC bias, and ages faster), give 2.0-2.2s nominal.
Worst case, every term a datasheet or purchase figure: C +-10%
tolerance, +-15% over -40..125C (X7R's whole range), -5% bias and
aging; R +-1%; and the one-shot's Rext/Cext I/O leakage, +-0.25uA
against a ~2.3uA mean charge current through 1M, +-11%. That is
1.3-3.1s. Firmware kicks at 5 Hz (a rising edge every 200 ms), so the
margin is 6.4x at the minimum window, and wdt_kick.h's 900 ms heartbeat
timeout plus one kick period (1100 ms) still lands inside the 1.28s
minimum - tests/host/test_wdt_kick.c asserts it, with 180 ms to spare.
A wedged controller loses the rail within 3.1s - 0.26 C of overshoot on
a 60 kJ/K kiln at 5 kW, against a runaway timescale of ~16 minutes.

The leakage term is the price of 1M: at the old 100k it was 0.8%. The
way to buy it back is a smaller R with a bigger X7R cap, and every 1206
X7R of 10uF or more at LCSC is Extended (+$3 feeder) - as is a single
2.2uF X7R 0805, which is why two 1uF from the line C5/C37 already use
sit in parallel instead. R46 moves from C149504 (100k) to C17514 (1M),
same UNI-ROYAL 0805 family and JLCPCB Basic, so the swap adds no fee;
C49 is a second placement from an existing line. U10 remains the one
Extended-and-not-Preferred part in this block, +$3. Note the BAT54S it
replaced was Extended-but-PREFERRED, i.e. fee-free - removing it saved
nothing. See gen_jlc.LCSC's note on that distinction.

Q3's gate drive becomes Q's VOH, ~3.2V, which finally clears the 2.5V
point where the AO3400A guarantees ANY Rds(on) - the corner the pump
block flagged and could not reach.

Fail-safe polarity is unchanged and now has three independent reasons to
hold: no edges -> window expires -> Q low; R48 pulls B low whenever the
MCU drives nothing, so a floating CMOS input cannot self-trigger the
one-shot during boot ROM, flashing or reset; and with U10 unpowered
entirely, Q3's gate simply floats, which R47 already answers.
Then Q3 off -> R47 pulls SSR_PG to +5V -> Q4 off -> rail dead.

R49 pulls WDT_OK down. The earlier note here claimed no pulldown was
needed because "with U10 unpowered Q3's gate simply floats, which R47
already answers" - that is wrong, and wrong in the fail-DANGEROUS
direction. R47 holds SSR_PG, not Q3's gate, and it only wins while Q3
is off. A floating gate is not off: the AO3400A's Vgs(th) floor is
~0.65V, so any leakage or coupling that lifts WDT_OK above it turns Q3
ON, which pulls SSR_PG down through a few tens of milliohms against
R47's 100k, which turns Q4 ON and makes the SSR rail LIVE with no
firmware and no watchdog. The case is real rather than theoretical:
+3V3 is U2's output and +5V is not, so any +3V3 failure (LDO dead,
rail shorted, U2 in thermal shutdown) unpowers U10 while leaving the
SSR rail's supply intact. 100k against Q's push-pull VOH costs 32uA
and defines the node whenever U10 does not.

## C38 (design.py line 1519)

Rotated 90 deg, and its pins swapped to match: U10's pins 6 and 7 are
0.5 mm apart on the same edge, so with the cap lying horizontal one of
the two timing nets had to cross the other's pad and the router could
not seat it. Perpendicular, pin 6 (CT_N) fans south to pad 1 and pin 7
(CT_P) fans north to pad 2, and the two runs diverge instead of meeting.

Route order matters here as much as the rotation. WDT_OK leaves pin 5,
just below pin 6, and has to reach both Q3 (south-west) and its pull-down
R49 (north-east). Routed before the timing nets, it took the short way to
R49 - east between C38's two pads - and walled pin 6 off from pad 1:
WDT_CT_N went round by x=40 and back, 55 mm and 8 vias for a 3 mm
connection, with WDT_CT_P at 24 mm / 4. Routed WDT_CT_N, then WDT_CT_P,
then WDT_OK (`make pcb-route NETS=WDT_CT_N,WDT_CT_P,WDT_OK` - the router
takes nets in the order given), both timing nets seat on F.Cu with no via
(5 mm and 13 mm) and WDT_OK passes under C38 on B.Cu to R49 instead
(19 mm, 3 vias). Re-route this group in that order. route.py keeps U10's
pad-escape stubs through a rip-up, and the new WDT_OK joins its stub
part-way along, so trim the stub back to that joint or DRC reports it
dangling.

## C39 (design.py line 1529)

Rail on pin 1, not pin 2: KiCad's R symbol runs its pins
vertically, and a rail hanging off the BOTTOM pin is
power_path()'s "exactly wrong" case - the port comes back up
past the pin and its bar lands on the part's own fields. The
PCB does not care which pad is which here; C38 is due north.

## Q4 (design.py line 1547)

High-side switch for the SSR gate-drive rail. AO3401A (P-channel,
SOT-23, LCSC C15127, JLCPCB Basic): source on +5V, gate on SSR_PG,
drain IS SSR_EN. It carries gate drive only - 0.5 mA into R18 and
Q7's gate (since B.4; B.2 also fed the two opto collectors from it) -
which is why a 30 V part is still the right one here while Q5/Q6/Q7
and Q9 stand off the 24 V rail and are 60 V parts.
Pin order from KiCad's own Transistor_FET:AO3401A symbol
(extends TP0610T): 1 G, 2 S, 3 D.

## R47 (design.py line 1557)

Q4's gate pull-up: the fail-safe. Nothing holding SSR_PG down means
SSR_PG = +5V means Q4 off means no gate-drive rail. 100k keeps Q3's load at
50 uA (see the arithmetic above) while staying stiff enough that Q4's
own gate leakage moves the node by only ~10 mV.

## SJ2 (design.py line 1564)

Bring-up defeat: shorts SSR_PG straight to GND (through Q3's own
source net), holding Q4 on and bypassing the watchdog gate entirely so
the SSRs work before the firmware kick task exists. Silkscreened
"WDT DEFEAT" - see gen_pcb.py SILK. MUST be removed (left open) in
service - this is a foot-gun by design, not a normal-operation jumper.

## U6 (design.py line 1574)

--- Aux output bank (vent / purge / spare) --------------------------
ULN2003A: 7 Darlington channels with integrated freewheel diodes to COM,
and a JLCPCB *Basic* part - so it replaces ~19 discrete parts at zero
feeder fee. Pin order (SOIC-16, confirmed against KiCad 10's own
Transistor_Array:ULN2003A symbol): I1..I7 = 1..7, GND = 8, COM = 9,
O7..O1 = 10..16 (note O1 is pin 16, so the outputs run backwards).

Channel order follows the copper, not the AUX numbering: AUX1 (vent) is
channel 3 (I3/O3, pins 3/14), AUX2 channel 2, AUX3 channel 1 (pins 1/16).
U6's outputs face J10 at the same y as their inputs, so O3 (top) lands on
J10.2 (top) and the three output traces fan straight across with no via;
numbering them AUX1=channel 1 put O1 at the bottom of U6 feeding J10.2 at
the top, and every output crossed. The GPIOs follow the same rule from the
other end: U1 pin 9 reaches U6's top input by the B.Cu lane north, U1 pin
22 (the module's bottom edge) reaches the bottom input by the route south of
LCD_CS, so AUX1 (vent) is on pin 9 and AUX3 on pin 22. They are just GPIOs to
firmware; reassigning them cost a Kconfig default, while uncrossing the
copper the other way would have cost vias the B.Cu side has no room for.
R23 (AUX1) sits beside U6's top input and R25 (AUX3) beside the bottom one.

COM goes to AUX_VP, its own screw terminal, NOT the board's +5V: a gas
purge solenoid is realistically 12V or 24V DC and the ULN is rated 50V /
500mA per channel. A solder link (SJ1) ties AUX_VP to +5V for plain 5V
relays. The buzzer deliberately keeps its discrete driver (Q2/D4/R8/R11)
so a 5V buzzer and a 24V solenoid never share a COM rail.

R23-R25 hold the inputs low while the ESP32 pins are high-impedance at
boot - a floating Darlington input must not energize a solenoid. Per
REV-B-NOTES.md SS6, 10k is sufficient: worst case (ignoring the ULN's
own nominal-only internal pulldowns) V_in(max) = 50nA x 10k = 0.5mV,
~1000x margin under any threshold that would turn a channel on, and
the three AUX GPIOs carry no pull-up at reset.

Designators: the task brief called these R20-R22, but Task 7 (SSR
optocoupler channels) already consumed R20-R22 - verified against the
live COMPONENTS dict before adding these. Using R23-R25 instead.

## LED1 (design.py line 1646)

--- WS2812B status LED ---------------------------------------------
R3 / LED1 / C10 west to east with D3 below, in the quietest part-free
window this board has: 0.26 mm/mm2 of track and zero vias, against
0.53 mm/mm2 and eight vias where the cluster used to sit. Measured, and
measuring it correctly is the whole story of where this went.

It moved out of the strip above J7 because a 5 x 5 mm PLCC4 is wider
than three pin pitches and was sitting squarely on the label band for
J7's pins 5, 6 and 7: `SDA` and `3V3` were pushed 2.60 mm onto the
connector body and `SCL` onto LED1's own outline, so the row printed as
`3V3 GND TX RX . . . GND` and counting from either end gave the wrong
pin - on the one header carrying I2C and a 3.3 V rail. No silk placer
can fix that (analysis/silkscreen-review.md §B); the part had to move.

Two candidate homes measured as EMPTY and were not, and both cost a
full re-route to find out:

the band south of the module (x 60..88, y 44..56) is U1's escape.
Forty castellated pads fan through it to the test-point row at y 57.
SPI_MOSI and SPI_SCLK could not reach TP4/TP5 and TC1_CS finished
unrouted.

the lane at the middle of the board (x 67..80, y 63..95) is the
nameplate's, and it is also the I2C corridor from the test-point row
down to the pull-ups and J7 - 220 mm of track through it. I2C_SDA and
I2C_SCL could not reach the ADE7953.

The reason both looked free is a measurement bug worth not repeating:
the density probe counted a track only if an ENDPOINT fell inside the
window, so a corridor - which by definition is traces passing straight
through - read as zero. Worse, it was run against the board from the
failed build, where the very nets in question were missing. Measure
against a FULLY ROUTED board, and clip each segment to the window
(Liang-Barsky) rather than testing its endpoints.

It was at (92.25, 97.45) until this revision, in the 5 mm strip above
J7 - which is J7's PIN-NAME strip. A 5 x 5 mm PLCC4 is wider than three
pin pitches, so LED1 and its 330R covered the label band for pins 5, 6
and 7 outright: `SDA` and `3V3` were pushed 2.60 mm onto the connector
body and `SCL` onto LED1's own outline, and the row printed as
`3V3 GND TX RX . . . GND` - a 10 mm hole, so counting from either end
gives the wrong pin on the one header carrying I2C and a 3.3 V rail.
No silk placer can fix that; the part had to move. See
analysis/silkscreen-review.md §B.

So it lands one lane west and one band north of where it was: x 66..82,
y 85..95, which is toward the centre of the board (the old spot was
22 mm east and 27 mm south of it), in front of the panel rather than
behind a connector housing, and clear of every pin-name band. The
800 kHz single-wire protocol does not care about the run from LED_DATA's GPIO.

## D3 (design.py line 1704)

Silicon, not the SS14 Schottky this was, and the buck is the reason.
VLED = +5V - Vf, and the WS2812B needs 0.7*VLED to stay under the 3.3V
the ESP32 drives. On the old unregulated rail an SS14's ~0.3 V left
VLED at 4.3 V (VIH 3.01 V) only because the input sagged; on a regulated
5.0 V rail the same diode gives VLED 4.7 V and VIH 3.29 V - a 10 mV
margin, i.e. none. A 1N4148W drops 0.65-0.85 V across the WS2812B's
5-60 mA range, putting VLED at ~4.15 V and VIH at ~2.9 V, comfortably
under 3.3 V and still well above the part's 3.5 V VDD minimum.

What regulating removed is the TRADE, not the drop. The review's
"trimming the PSU up to help the SSR/relay drops hurts the LED" is gone
- VLED no longer moves with the installer's trim pot - so a fixed drop
is now a real fix rather than a hedge, and the 74AHCT1G125 the review
offered as the alternative is not needed.

## R12 (design.py line 1725)

--- Protected dry-contact inputs (lid / gas flow / spare) -----------
Generalises rev A's single lid-switch filter (below) to three
identical channels, all on J11, plus one SRV05-4 TVS array covering
them. 1k series, 10k pull-up to +3V3, 100nF to GND per channel. Open
contact reads HIGH = "open/inactive", so a broken wire, a pulled
connector or a failed-open switch all read "open" and fail safe.
IN1 = lid, IN2 = gas-flow interlock, IN3 = spare - see
docs/pin-assignments.md. Wire a dry contact between each channel
and J11.4 (GND).

R13 replaces the ESP32's weak ~45k internal pull-up with a stiff 10k,
so an open switch holds the node high against far more leakage and
capacitive pickup. R12 limits fault/ESD current into the pin, and C12
sees R12||R13 (~0.9k) with the switch closed - a ~1.8 kHz corner
(~90us), rising to ~160 Hz (10k x 100nF) with it open. Fast enough to
leave mechanical bounce to the firmware, which samples at 500 ms;
slow enough to swallow EMI transients. Closed-switch level is
3.3V x 1k/11k = 0.30V, well under the ESP32's 0.25 x VDD (0.83V) V_IL.

Rev A skipped a TVS (a unique Extended part / $3 feeder fee for one
input); rev B's externally-exposed net count goes from two to ~ten,
so one SRV05-4 array (D5) now covers all three raw inputs upstream of
the series resistors. NOT extended to the thermocouple inputs
(TC1_P/N, TC2_P/N, Task 6) - array leakage into a ~40 uV/C source is
an accuracy error, not protection.

D5's channels follow the copper, as U6's do: the SRV05-4's four IO pins
are identical steering-diode pairs, so IN1_RAW takes IO1 (pin 1),
IN2_RAW IO4 (pin 6) and IN3_RAW IO2 (pin 3), leaving IO3 (pin 4) idle.
On pin 4, the east side facing J11, IN3_RAW had to cross IN2_RAW to
reach R28 west of D5 and spent 3 vias doing it; on pin 3 it stays on
F.Cu with none.

All three inputs stay on ADC1-capable GPIOs, which keeps a
resistance-monitored interlock loop possible without a respin (see
docs/application-roadmap-and-pcb-provisions.md). IN3's is on U1 pin 18,
on the bottom edge facing this block; see U3 for why TC1_CS gave it up.

Designator note: the brief that originated this block called for
R23-R26; R23-R25 were already consumed by Task 8's ULN2003 pulldowns
by the time this landed, so the second and third channels use the
next free run, R26-R29, instead. Re-verify against the live
COMPONENTS dict before reusing numbers near here - a duplicate key
silently overwrites the earlier component.

Placement: R12/R13/C12 (channel 1, née rev A's lid filter) keep their
original spot in the free band between LED1 and J7. Channels 2 and 3
extend the same schematic row/PCB band eastward; D5 and J11 sit just
past them. See gen_sch.py SCH_AT for the >=20mm spacing rule that
keeps facing pin-label stubs from merging nets (Tasks 7, 8).

## C23 (design.py line 1778)

Channel 2's filter cap, in channel 2's row. It used to sit at
(35.0, 115.0) - 20 mm west of its own R26/R27, on the far side of
channel 3 - which is what made IN2 the longest signal net on the board
(158.6 mm routed, 108.3 mm ideal) and hung a westward spur across
channel 3's row. x 58.9 is the only slot that exists for it: R27's
courtyard ends at 56.7 and J11's begins at 61.0, so the 0805 lands with
~0.5 mm either side. It takes IN2's ideal from 108.3 mm to ~94 mm and
makes the three dry-contact channels three clean rows.

## U7 (design.py line 1810)

--- CT current sensing (ADE7953, I2C, current-only) -----------------
Two current channels, one per SSR zone. I2C rather than SPI: the bus
exists for the expansion header anyway (Task 11), so the chip costs
zero extra GPIOs.

NO MAINS ON THIS BOARD. The voltage channel (VP/VN) is unused: held at
GND by R60/R61 and brought out to nothing. Rev B.3 dropped J13, the DNP
SELV header that kept an off-board isolated AC accessory possible, as
true power measurement is not a planned feature. IRMS is reported
against a configured nominal mains voltage (REV-B-NOTES.md SS1:
IRMSA/IRMSB are computed entirely within the current signal path and do
not depend on VP/VN).

Every value below is taken from hardware/kicad/datasheets/REV-B-NOTES.md
(ADE7953 Rev. C), which OVERRIDES the task brief's guessed values.
Designators were renumbered against the live COMPONENTS dict: the
brief's R27-R33/D8 collide with Task 9 (R27/R28/R29) and Task 7 (D5).

Interface strapping (REV-B-NOTES.md SS3, correcting the brief):
pins 7/8 PULL_HIGH -> +3V3 direct, no resistor (Table 5: "internal
node pins", not interface-select - the brief's framing was wrong)
pin 14 PULL_LOW -> GND direct, no resistor; routed into the EP land
pin 25 SCLK -> +3V3 via R37 10k pull-up (interface-select: 1 = I2C)
pin 28 ~CS -> +3V3 via R38 10k pull-up (interface-select: 1 = I2C/UART)
pin 27 MOSI/SCL/Rx -> I2C_SCL, pin 26 MISO/SDA/Tx -> I2C_SDA (the
ACTUAL bus signals - the brief had these swapped onto pins 25/28)
10k is Figure 35's Test Circuit value; the datasheet gives no
resistor spec for 25/28 (COULD NOT VERIFY #3), only "pulled high".
Both pins are static logic inputs nothing else drives, so the value
isn't critical - resistors instead of hard ties buy an override path
for bring-up or a future SPI experiment for 2 cents.

I2C address is fixed at 0x38 (no address pins, REV-B-NOTES.md SS3) -
collides with a PCF8574A expander and some touch controllers on the
Task 11 expansion header. Nothing else on THIS board's bus conflicts.

Pins left unconnected: 1 ZX (voltage zero-cross, meaningless with no
voltage channel), 20 ~REVP (needs both channels), 23/24 CF1/CF2
(calibration frequency outputs, unused). 21 ZX_I and 22 ~IRQ are also
left NC for now - REV-B-NOTES.md SS1/SS3 recommend routing both to a
GPIO (ZX_I for the datasheet's recommended synchronous IRMS read;
IRQ for the power-up-complete signal) but no GPIO is allocated to
this task's scope; a bare test point is a candidate for Task 13.

EP (pin 29) is a ground pin, not just a thermal tab (REV-B-NOTES.md
SS2, Rev. C p.10/p.68: "Connect the pad to AGND and DGND") - tied GND.

2026-10-26, the EP's vias and the stencil. The library footprint puts
nine 0.83 mm paste windows on the 3.1 mm pad with 0.2 mm webs, so its
four GND vias could only land in paste, where an open barrel wicks the
joint during reflow (PCB review 2026-10-05 item 4; JLC's DFM flags it
as "lead to hole distance"). The fab-side answer is epoxy fill-and-cap,
a per-order surcharge on four layers. The board-side answer, taken
here: four 1.1 mm paste windows at (95 +/- 0.9, 72 +/- 0.9) on a 0.7 mm
cross web (50 % coverage, was 64 %), the copper pad with NO F.Mask
layer of its own, and four 1.2 mm F.Mask apertures over the paste
windows. The 0.6 mm web of mask between the apertures covers the vias,
which moved onto the cross - (95, 70.9), (95, 72), (95, 73.1) and
(96.1, 72), 0.5 mm pads on 0.3 mm drills so the mask has 0.05 mm of
margin over the copper and 0.15 mm over the hole. They are ordinary
tented vias now, and the fab-side option is unnecessary. The west arm
carries no via because the I2C_SCL escape runs south on B.Cu at
x 93.5/93.75 under the pad's west edge. Both edits live in the BOARD's
copy of the footprint; "Update Footprint from Library" in KiCad would
put the nine windows back, so don't. gen_pcb.EP_VIA_GRID keeps U7 as
the one pad check_via_in_pad.py still exempts.

## general (design.py line 1864)

19 CLKOUT is the far side of the on-chip oscillator's
inverter and exists only to hang a crystal off. Y1 is
now a powered oscillator driving CLKIN as a logic input
(datasheet p.9: "An external clock can be provided at
this input"), so nothing drives back into 19 and it is
left open. ADE_CLKOUT is gone with it.

## Y1 (design.py line 1874)

3.579545 MHz clock. A packaged OSCILLATOR (LCSC C2838127, YJX
TFOM3.579545M4RHKCNT2T, SMD3225-4P), not the parallel-resonant crystal
plus two load caps this used to be. The swap is the fix for the
oscillator loop, and the reasoning is worth keeping because it inverts
the usual default.

A crystal is normally the right answer - it costs a tenth as much, draws
microamps against this part's 5 mA, and the IC's own inverter is
characterised for one. Every one of those advantages is absent here.
Cost is $0.23 on a $19 BOM; power is 5 mA beside the ESP32's 240 mA on a
mains-fed rail; and this is a current-only metering block whose ±50 ppm
is 100x better than an IRMS reading needs.

What is present is the one thing a crystal demands and this board cannot
give: a short loop. 3.579545 MHz is a low frequency, so the quartz blank
is large and every 2-terminal part at this frequency is HC-49S - 19.75 mm
of pad on our old hand-solder land, 13.00 mm even on the standard one.
U7's ring is entirely VINTA/VINTD/VDD/REF decoupling that ADE7953 Rev C
p.67 says must stay closest to the chip, so nothing that size fits beside
it and the crystal sat 19.5 mm away with its load caps 26 mm the other
side of the IC - roughly 40 mm per leg, four vias each. At 3.58 mm this
part sits 2.52 mm from CLKIN, and the output is a driven CMOS line rather
than a high-impedance resonant node, so it has no loop to keep short at
all. It also deletes C26 outright and frees C25 to be its decoupler.

Pin 1 is left OPEN, and that is from the datasheet rather than from the
convention: the Measurement Circuit's switch table gives H -> oscillation
out, OPEN -> oscillation out, L -> High Z. Enabled when floating, so no
pull-up. Pinout confirmed twice over - the datasheet's pin table and
LCSC's own symbol both give 1 Tri-state / 2 GND / 3 OUT / 4 Vdd, which is
also what KiCad's Oscillator:ASE-xxxMHz symbol carries.

V_OH is >= 90% Vdd = 2.97 V against the ADE7953's 2.4 V V_INH, and the
15 pF max output load is far above CLKIN plus a few mm of track.

7.8 mm from CLKIN, not the 2.5 mm it will physically fit at, and the
difference matters. U7 is in FANOUT, so a ring of pre-seeded escape stubs
and plane vias reaches FANOUT[U7] + 1.25 = 3.0 mm past every pad and is
spoken for before the router starts. Parking the part at 2.5 mm sat on
it: 3 nets unroutable, a plane via with nowhere to go, and 11 DRC
clearance errors. This sits outside that ring, in the space the two
deleted 30 pF load caps used to occupy.

Being further away costs nothing HERE and that is the whole argument for
the part. OUT is a driven CMOS line, not a high-impedance resonant node,
so it is an ordinary signal with an ordinary length: the tight-loop
requirement that a crystal imposes - and that this corner of the board
cannot satisfy - simply does not exist for an oscillator.

## C25 (design.py line 1927)

Y1's supply decoupling, and the whole of it - an oscillator needs one
bypass cap and no load caps at all. This designator used to be one of a
pair of 30 pF crystal loads whose value was flagged in REV-B-NOTES.md
SS4/SS10#1 as an ASSUMPTION rather than a datasheet fact, because the old
crystal published no C_L: the 30 pF came from the notes' own worked "if
C_L turns out to be 20 pF" case, and it was an open bring-up item to be
settled by measuring startup margin on the first board. Moving to a
packaged oscillator retires that item outright rather than resolving it -
there is no C_L, no C_stray, and no startup margin for us to own. C26 is
deleted; the ADE7953's own datasheet shows 0.01 uF here and 100 nF is the
part already on this BOM.

## R30 (design.py line 1941)

~RESET (pin 2): REV-B-NOTES.md SS4 - Figure 35's Test Circuit shows a
10k pull-up to 3.3V with a 1uF cap to ground for a power-on reset
stretch (Figure 78's application circuit shows nothing on this pin -
it's application-dependent). Datasheet minimum low pulse is 10us; a
software reset and the datasheet's own reset interrupt are both
available if this network is omitted, but the stretch is cheap.


2026-10-26 (schematic review 2026-10-22, E3): `ADE_RESET` is a
hierarchical net now and reaches U1's IO37 (module pin 30, the one GPIO
the quad-PSRAM module left spare; `KILN_PIN_ADE_RESET`). The RC stays
and still does the power-on stretch by itself; the GPIO is an input
until firmware needs to recover a wedged I2C engine, when it drives low
for >= 10 us and lets go. Nothing is lost on a build that never touches
it, which is why the RC was kept rather than replaced by the pin.

## C27 (design.py line 1960)

VINTA/VINTD/REF/VDD decoupling - REV-B-NOTES.md SS4 (Table 5, cross-
checked against Figure 78): each of VINTA, VINTD and REF (all internal
LDO/reference OUTPUTS to be decoupled, never driven) gets 4.7uF || 100nF;
VDD gets 10uF || 100nF. That's 8 physical capacitors, more than the
brief's 4 pre-allocated designators (C27-C30) provided for, so the
extra four are allocated sequentially from C33 as the task instructions
direct. The ceramic (100nF) of each pair is the one to place closest to
the IC per the datasheet's own layout guidance (Rev. C p.68); exact
placement is Task 14's job.
Placed on 2026-10-23 (PCB review 2026-10-05, items 1 and 2): C36 is
1.0 mm from VDD pin 17 and C35 1.9 mm below it, east of U7; the CT
filter caps C31/C40 stand on end against IAP/IAN (1.3 / 1.4 mm) and C32
against IBP (0.6 mm); VINTD's pair stands on end 4.4 mm west of pin 3,
fed straight across between C31's pads and under I2C_SDA on B.Cu; REF's
pair sits south at ~6 mm. RXD0/TXD0 used to run past U7's west side and
were re-routed to make the room.

## R31 (design.py line 1993)

Channel A burden + anti-alias. The ADE7953's current inputs are
bipolar, referenced to AGND directly - no mid-rail bias divider like a
single-supply ADC (this is not in REV-B-NOTES.md; it's how a
differential current-sense front-end normally works, and the brief's
amended text already reflects it). R32/C31 form a ~4.8 kHz pole, well
above the 60 Hz fundamental and its usable harmonics, well below the
modulator rate.

Sizing (not from REV-B-NOTES.md - the notes don't cover the CT/burden
network, only the ADE7953 itself): a 2000:1 current-output clamp
(100A:50mA, e.g. SCT-013-000) against the ADE7953's +-500mV full-scale
differential input. 100A rms -> 50mA rms -> 70.7mA peak, so
0.5V / 70.7mA ~= 7.1 Ohm is the value that puts 100 A exactly at full
scale.

5.1 Ohm, not that 7.1 or the 6.8 this was: JLCPCB stocks no 6.8 Ohm
resistor in its Basic or Preferred libraries in ANY package, so 6R8 was
costing a $3 feeder fee to hold one value. The fee-free ladder either
side of it is 4.7, 5.1, 10 - and 10 is not available, since 70.7mA
across it is 707mV against a 500mV full scale, i.e. the input clips at
~71 A.

What 5.1 Ohm costs is range, not accuracy: 100 A now reads 361mV, 72% of
full scale rather than 96%, and full scale moves out to ~139 A rms. On a
part with the ADE7953's dynamic range that is not a measurable loss, and
a kiln element circuit does not go near either number. The alternative
that preserves 6.8 exactly is 10 || 22 (= 6.875 Ohm, both Basic), at
four placements instead of two on a differential sense node - not worth
it for range nobody uses.

This scaling is a calibration constant the firmware will need, and it
CHANGED with this resistor - see docs/pin-assignments.md (Task 16).

## R59 (design.py line 2037)

Channel A's RETURN leg (review A10). Both channels used to run
single-ended - signal on IAP, IAN strapped to GND - and that is fine on
channel B but not on channel A, because the asymmetry is inside the
chip: ADE7953 Table 5 (p.20) allows +-500 mV on IB single-ended and only
+-250 mV on IA. With the 5R1 burden that is 34.7 mA rms, so a 2000:1 CT
full-scales at 69 A rms on channel A against 139 A on channel B - a 2x
difference that is invisible in the netlist, wrong in the README, and
would land in firmware as one shared calibration constant.

Driving IAN as a real input recovers the full +-500 mV differential.
R59/C40 mirror R32/C31 exactly so both legs see the same 1k/33nF
anti-alias corner - an unmatched pair converts common-mode into
differential, which is the whole thing this is buying. R33 stays: with
IAN no longer strapped to GND it is what still references the floating
CT secondary, and at 1k against the 5R1 burden it does not load it.
East of D6, not south of R33, and the difference is what makes CTA_N
routable at all. CTA_N is a five-pad chain that otherwise runs
monotonically east - R31 (94.4), R33 (97.1), D6 (101.9), J12 (114.0) -
and (98.0, 91.0) hung a southward spur off the middle of it into a
column already blocked by R36. CTA_N then failed to route under every
ordering tried: promoted with the analog group, promoted alone, and
with only ADE_REF promoted. That is geometry, not ordering.

At x 106.3 it is simply the next link east. The cost is CTA_FN's run
back to U7 pin 6, which gets longer - and CTA_FN is the FILTERED node,
shunted to ground by C40, so it is the leg that can afford distance.
CTA_N carries the raw burden voltage and cannot.

y 89.0 rather than 91.0, and that is silk rather than copper: J12's `A+`
mark is y-locked to its own screw at 92.00 and can only move in x, with
J12's body immediately east of it. At y 91.0 this resistor took the only
x the mark had and it printed under the block it names. y 89.0 sits in
the 3.58 mm of clear row between the `A-` and `A+` marks.


## R65

Channel A's second ground reference (schematic review 2026-10-05, item
2). R33 alone referenced the floating CT secondary from the CTA_N side,
which put the whole burden voltage on IAP and only the filter leakage on
IAN: at 50/60 Hz the 33 nF caps are open circuits next to 1 k, so the
"differential" channel still clipped IAP's +-250 mV at about 69 A even
with R59/C40 in place. A second 1 k from CTA_P to GND splits the burden
voltage symmetrically, +-V/2 on each pin, and the pin limit becomes the
+-500 mV differential limit - 139 A nominal on a 2000:1 CT, the same as
channel B. Two 1 k in series across a 5R1 burden is a 0.25 % load, far
below the burden's own 1 %. Mirrors R33: same value, same LCSC part,
hangs off CTA_P the way R33 hangs off CTA_N.

## R60 (design.py line 2076)

ADE7953 voltage-channel inputs. Nothing drives them, so without these
VP and VN are floating PGA inputs and the datasheet gives no guidance
for that state. 1k to GND on each defines them (REV-B-NOTES.md SS1,
"Handling of the unused voltage inputs").

## D6 (design.py line 2099)

Spec SS5.5's second SRV05-4 (the first, D5, covers the dry-contact
inputs). NOT on the thermocouple inputs - array leakage into a
~40uV/degC source is an accuracy error, not protection. SRV05-4
pinout matches D5's: 1 IO1, 2 GND, 3 IO2, 4 IO3, 5 VP(+3V3), 6 IO4.

## general (design.py line 2130)

LCDWIKI 4.0" MSP4021 (ST7796S + XPT2046 touch), grown from
rev A's 8-pin display-only header (Task 11). Pins 1-8 keep
rev A's assignment (see below); 9 is the panel's SDO (rev A
left it unwired - the firmware never read from the
display); 10-14 are the touch panel. The XPT2046 lives on
the display module, not this board - T_CLK/T_DIN/T_DO ARE
the shared SPI2 bus (SPI_SCLK/SPI_MOSI/SPI_MISO), so only
T_CS and T_IRQ cost new GPIOs (Task 3). R39-R43 damp a bus
that now multi-drops four devices (LCD, TC1, TC2, touch)
at 40 MHz.

VCC accepts 3.3-5V per the module's own manual, and every
reference wiring diagram in it (incl. 3.3V-logic STM32
boards) ties VCC to 5V while driving CS/RESET/DC/MOSI/SCK
directly from 3.3V GPIOs with no level shifter - so +5V
here needs no other board change. Moving off +3V3 also
takes the backlight/panel current off the AMS1117 (U2)
entirely rather than through its LDO drop.

## R39 (design.py line 2156)

--- Touch series damping (Task 11) -----------------------------------
T_CLK/T_DIN/T_DO are the shared SPI2 bus; T_CS/T_IRQ are dedicated
GPIOs (Task 3). All five get 33R series damping since the bus now
multi-drops four devices at 40 MHz.

## R50 (design.py line 2175)

--- Chip-select pull-ups (review A4) ---------------------------------
None of the four SPI chip selects had a pull-up, and none of their GPIOs
has a pull at reset (ESP32-S3 DS Table 2-1), so every slave sees a floating
CS from power-on until firmware configures the pin - and firmware only
ever drove two of them. On a bus that multi-drops four devices at 40 MHz
that is bus contention during the display's first bursts, with two
MAX31856s and an XPT2046 free to decide they are selected.

Placement is nearly free here because +3V3 is a PLANE (In2.Cu): a
pull-up needs one signal tap and one plane via, not a routed rail. The
two TC pull-ups therefore sit in the empty east block rather than in the
6 mm SPI channel between U3 and U5, which is the one lane on this board
that must stay clear (see the thermocouple geometry note above).

## R54 (design.py line 2200)

--- Display series damping (review A5 + C "no damping on the loom") ---
R39-R43 damped the five TOUCH lines and stopped there, leaving the four
fastest nets on the board - SCLK, MOSI, DC and CS at 40 MHz - driving a
loom to a door-mounted panel with nothing in series. R54-R58 finish the
job with the same 33R the touch lines already use.

R56 is review item A5 and is the one that is not just damping. J5 pin 9
is the panel's SDO, hard-wired onto the shared SPI_MISO with both
MAX31856s. The ST7796S datasheet never states that SDO goes high-Z when
the panel is deselected, this module carries no series resistor of its
own, and if it does hold the line the thermocouples cannot be read at
all. 33R is the hedge: it damps like the others if SDO does tri-state,
and if it does not, R56 is a component to lift instead of a track to cut
on every board. Bring-up: scope TP6 with the panel plugged in while TC1
is selected.
R54 and R58 sit at each other's obvious slots, and that is the point.
J5's pins 5/6/7 are DC / MOSI / SCLK at x 34.16 / 36.70 / 39.24, so the
three damping resistors have to run in that same order west to east or
their three ~8 mm nets cross each other in the 6 mm between this row
and the connector. They did: with SCLK at x 34.5 and DC at 38.5,
LCD_MOSI_R routed 102.7 mm over 12 vias for an 8.4 mm net, LCD_DC_R
67.3 mm and LCD_SCLK_R 59.7 mm - 205 mm of excess and 17 vias between
them. R39-R43 one row east do the identical job uncrossed and land
within 1.5 mm of ideal, which is what says this was ordering rather
than congestion. Move one of these two and move the other.

## general (design.py line 2250)

pin 6 carried the raw lid-switch input in rev A; the lid
moved to its own terminal (J11) in Task 9. Pins 5-8 carried
VENT/(unconnected)/AUX_A/AUX_B through Task 10 - all
dangling single-pin nets, nothing on the board actually
drove them (the real VENT output is AUX1, on U6). Task 11
re-points 5-8 to I2C, giving the bus a 0.1" tap alongside
the Qwiic connector (J14) and finally retiring AUX_A/AUX_B.

## J14 (design.py line 2259)

--- I2C expansion (Task 11) ------------------------------------------
The `_MountingPin` symbol earns its place: the footprint's two metal
ears are one pad named MP, and the plain Conn_01x04 has no pin to
attach a net to, so they shipped as dead copper. They are the cable's
retention - a Qwiic lead is pulled on by hand - and soldering them to
the GND pour is what makes them hold. `pins` is keyed on pad NAME, so
"MP" reaches both ears.

## FID1 (design.py line 2295)

--- Fiducials --------------------------------------------------------
Optical alignment targets for the pick-and-place: 1 mm of bare copper in
a 2 mm mask opening, on no net, doing nothing electrically. The machine
knows where all 109 parts go in BOARD coordinates, but the board in the
fixture is never exactly at nominal - a fraction of a degree of rotation,
a couple hundred microns of offset, and some lamination/route scaling. It
finds these three, solves the transform, and applies it to every
placement.

JLCPCB panelises this board themselves and puts fiducials on the panel
frame, so an order without these is accepted and usually fine; what board
fiducials add is correction for THIS board's position within the panel.
Worth having at 0.5 mm pitch: U7 is a QFN-28 whose lands are 0.25 mm
wide, where 100 um of placement error is a real fraction of the pad.

Positions are measured, not eyeballed - each is the roomiest point in its
corner region, scored on distance to the nearest pad, track, via and
board edge (5.24 / 4.22 / 8.36 mm of clearance respectively, against the
~1.0 mm the mask opening needs). Three of the four corners, which is the
conventional arrangement and the reason no fourth is fitted: the set must
not map onto itself under a 180 deg rotation or a flipped board would
align cleanly and every part would go on backwards. These three are also
comfortably non-collinear (3292 mm2 triangle, shortest leg 79 mm), which
is what lets the fit resolve rotation and scale rather than just offset.

The pad carries no pin number in the library footprint, and transform_fp
only assigns a net to a NAMED pad, so `pins={}` leaves it netless by
construction. Keep it netless: it is a camera target, and tying it to a
rail would only invite a pour to reach it and kill the contrast.

## TP12 (design.py line 2391)

Out of J12's legend column entirely (review A2). The pad
used to sit at (106.5, 84.4) - halfway between the B+ and
A- screws, chosen because it was in nobody's ROW. That was
the wrong question. The pad fitted; its LABEL did not. A
test point's label is anchored 1.7 mm below its pad, which
put `CT A+` at x 104.5..108.5, y 84.9..86.5 - inside the
strip from x 106.4 to J12's body at 108.68 that the CT
block's per-terminal legends own, and 0.4 mm above `A-`.
The CTA_N screw therefore read as both `CT A+` and `A-`,
on a terminal where getting it wrong means a CT wired
backwards. The four legends are y-locked to their own
screws and cannot step around it, so the test point moves.

STAYS at (106.5, 84.4), and review A2 is NOT fixed this
rev. Three homes were tried and the ADE/CT block cannot
absorb the test point in any of them - it got tighter this
rev, not looser, because A10's differential return (R59,
C40) and the VP/VN bias pair (R60, R61) all landed in it:

(86.0, 93.0)  open board SW of the ADE - CTA_N failed.
CTA_N now reaches R59 as well as R33 and
J12, so it runs south through exactly the
ground a 10 mm CTA_P stub has to cross. It
failed even PROMOTED to route first, which
on this board means the lane is blocked by
geometry, not by ordering.
(85.0, 83.5)  hard against R32, a 1-2 mm stub - ADE_VP
failed instead.
ditto, with ADE_VP/ADE_VN promoted - ADE_RESET failed
instead. The block is saturated: each
promotion only moves the failure to
whichever net loses the lane.

So the pad is between J12's B+ and A- screws, in nobody's
ROW - which was the right answer to the wrong question,
because the pad fits and its LABEL does not. See
gen_pcb.TP_LEGEND_OK for what that costs and what would
actually fix it.


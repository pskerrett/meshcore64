#lowercase
#linestep 10
header:
	rem ***********************************
	rem meshcore 64 - c64 companion client
	rem
	rem talks meshcore's binary companion
	rem protocol (not meshtastic's text
	rem protocol) over the user port rs232
	rem at 600 baud. pairs with a heltec v3
	rem "companion_radio_usb" build using
	rem -d serial_baud_rate=600 wired to
	rem the userport instead of usb.
	rem
	rem 1.2c: handshake, channel list
	rem (f1), per-channel chat, cart leds.
	rem contacts / direct messages yet.
	rem ***********************************
	:
	:


initialize:
#lineskip 500
	rem **initialize**
	rem *** OPEN THE RS-232 CHANNEL FIRST - THIS MUST COME BEFORE ANY
	rem *** dim OR VARIABLE ASSIGNMENT.
	rem opening device 2 allocates the kernal's two 256-byte rs-232
	rem buffers by lowering the top of basic memory, and that performs
	rem an implicit CLR -- every variable and array defined beforehand
	rem is wiped. we used to dim fb() and set hs/lt/s0/m0 above this
	rem line, so they were all silently thrown away: fb() was then
	rem auto-created at the default 11 elements on first use, and the
	rem parser died with "bad subscript" the moment a payload reached
	rem byte 11. (im$(9) hid the same bug, because the default 11
	rem elements happened to be enough for it.)
	rem **startup light show - the ONE thing allowed before the OPEN.**
	rem all six lamps sweep here, pb1/pb2 included, because the rs-232
	rem link does not exist yet: rts and dtr are ours to borrow until the
	rem kernal claims them. the open below takes them back, and from then
	rem on we only ever drive the four safe lamps (pb3-pb6) -- driving rts
	rem low once the link is up tells the peer to stop sending and kills
	rem reception stone dead.
	rem this is allowed above the open only because the implicit CLR wipes
	rem zv/zs/zj/zd and nothing here is needed afterwards. do NOT put
	rem anything above the open that has to survive it.
	print"{lower}" : print"{clear}{white}MeshCore 64   v1.2d"
	print"------------------------------------"
	poke 56579,126 : zv = 2 : zs = 2
	for zj = 1 to 24
	poke 56577, zv
	if zv = 64 then zs = 0.5
	if zv = 2 then zs = 2
	zv = zv * zs
	for zd = 1 to 18 : next zd
	next zj
	poke 56577,0 : poke 56579,120 : rem lamps off, rts/dtr handed back
	open 2,2,3,chr$(7) : rem userport rs232 @ 600 baud
	rem **machine-language serial engine**
	rem basic needs ~50ms per received byte (get# alone benchmarks at
	rem 52ms), but at 600 baud a byte lands every 16.7ms -- a 3x deficit
	rem no amount of basic tuning can close. this 346-byte routine at
	rem $c000 drains the kernal buffer and assembles frames in ~50 cycles
	rem per byte instead, so basic only ever sees completed frames. it
	rem also steps the cartridge led animations (see below).
	for zi = 0 to 345 : read zd : poke 49152 + zi, zd : next zi
	get#2, rb$ : rem one arming call: the chkin that starts the receiver
	poke 52992,0 : poke 52995,0 : rem ml STATE=0, READY=0
	rem **cartridge leds, driven by the ml routine.**
	rem four leds on user port pb3-pb6 ($dd01 = 56577, direction $dd03 =
	rem 56579; 120 = %01111000). pb1/pb2 are the c64's rs-232 RTS and DTR
	rem outputs and are deliberately left to the kernal -- driving rts low
	rem tells the peer to stop sending and kills reception stone dead
	rem (confirmed in vice: transmit carried on, receive stopped the
	rem instant the first animation started). pb0/rxd stays an input too.
	rem the cart has six leds; we drive the four that are safe. basic
	rem only ever pokes a pattern index + a go flag, once per event -- the
	rem ml steps the animation, because a poke costs ~7ms interpreted and
	rem per-loop animation in basic would eat 3-20% of the main loop.
	rem   52997 ($cf05) = pattern running flag   52998 ($cf06) = step index
	rem   index 0 = rx ripple, index 5 = tx flash
	poke 52997,0 : poke 56579,120 : poke 56577,0 : rem leds dark
	dim im$(9)
	rem ch$() caches the radio's channel names, indexed by the same
	rem channel_idx the protocol uses; "" means empty-or-not-yet-scanned.
	rem pk() maps a picker menu digit to a channel index, so the menu
	rem stays 0-9 even when the configured channels are sparse.
	rem cu() counts messages seen for a channel we are NOT watching, so a
	rem quiet screen can be told apart from traffic we are filtering out.
	dim ch$(39) : dim pk(9) : dim cu(39)
	rem **message history ring, 24 deep, shared across all channels.**
	rem hm$() holds the text, hc() the channel it belongs to, ht counts
	rem every message ever stored (slot = ht mod 24). one flat ring
	rem rather than a per-channel array on purpose: 24 string
	rem descriptors instead of 40x8=320 keeps basic's garbage collector
	rem out of trouble -- gc cost on this machine grows sharply with the
	rem number of live strings.
	rem **size the message ring from the ram that is actually left.**
	rem hard-coding it is how the build ended up dying with ?OUT OF
	rem MEMORY: a number that fits today stops fitting when the program
	rem grows. fre(0) goes negative above 32767 on this machine, hence the
	rem correction. ~50 bytes per entry (3 descriptor + 40 heap + 5 for
	rem hc), and 5000 held back for sh(), bk$/sp$ and working strings.
	zf = fre(0) : if zf < 0 then zf = zf + 65536
	hz = int((zf - 5000) / 50)
	if hz > 120 then hz = 120
	if hz < 8 then hz = 8
	dim hm$(hz - 1) : dim hc(hz - 1) : dim rp(14)
	rem **message archive, in the reu, one region per channel.**
	rem a line is 40 screen-code bytes, so 25 consecutive lines are
	rem exactly the 1000 bytes of screen ram and a page is ONE dma. nine
	rem regions: channels 0-7 get their own, higher channels share 7, and
	rem "All" gets region 8 and receives every line.
	rem no tag array is needed - regions are contiguous per channel - so
	rem depth scales with the reu instead of being capped by c64 ram.
	dim lw(8) : dim lf(8)
	rem bk$ = cursor-lefts, sp$ = spaces. used to back up over the prompt
	rem and overwrite it, so an incoming message can reuse the prompt's
	rem own screen row instead of leaving it blank above every message.
	rem doubling, not 80 concatenations: 5 jiffies instead of 66, and it
	rem leaves far less litter on the string heap. 7 doublings = 128 chars,
	rem comfortably over the 80 we ever use.
	bk$ = chr$(157) : sp$ = " "
	for zi = 1 to 7 : bk$ = bk$ + bk$ : sp$ = sp$ + sp$ : next zi
	rem frame payload goes in a NUMERIC array, not a growing string.
	rem the old "fb$ = fb$ + chr$(rv)" allocated a brand-new string for
	rem every payload byte, littering basic's string heap until the
	rem garbage collector stalled everything for seconds at a time --
	rem that, not the baud rate or the mesh, is what made a short
	rem message take ~30s to appear. an array store costs nothing and
	rem creates no garbage. it also skips pointless work: device_info
	rem is 82 bytes we never even read.
	hs = 0 : im = 0 : og$ = "" : oa$ = "" : ez = 0 : lt = ti : rj = 0 : rem rj = frames rejected as implausible
	ru = 0 : uk = 0 : lr = 0 : sb = 0 : cc = 0 : co = 0 : ck = 0 : ut = 0 : cf = 0 : ht = 0 : pr$ = "> " : rem channel, prev, cached, unread, sweep, history, prompt
	rem (title already on screen from before the open; CLR wipes variables,
	rem not the display)
	gosub reuDetect
	rem uk is in kb and a screen snapshot is exactly 1kb, so the slot
	rem count is uk -- less one, reserved to park the live screen while
	rem you are scrolling.
	rem uk kb of reu holds uk*25 lines of 40 bytes; split across 9 regions
	if ru = 1 then lr = int(uk * 25 / 9)
	rem str$ of a positive number carries a leading space, hence mid$
	if ru = 1 then print"REU ";mid$(str$(uk),2);"K - F5 scrollback ready"
	if ru = 0 then print"No REU - scrollback disabled"
	print"Arming RS-232..."
	tw = ti + 120 : rem ~2 second settle delay -- known c64 kernal rs232
	armWait: if ti < tw then goto armWait : rem quirk: bytes right after
	rem open can be lost/corrupted before the nmi-driven receiver is
	rem fully armed; give it a moment before trusting the link.
	print"Connecting..."
	gosub connect
	print"{13}Connected as ";nn$;" on ";cn$
	print"Radio fw: ";fw$
	print
	rem only offer f5 if there is actually an REU to scroll back into --
	rem the key handler already no-ops without one, but advertising a key
	rem that does nothing is worse than not mentioning it.
	if ru = 1 then print"F1 Channels   F5 Back   F7 Public"
	if ru = 0 then print"F1 Channels   F7 Public"
	print
	gosub setPrompt
	rem kick off a drain of anything already sitting in the radio's
	rem offline queue (messages that arrived before we connected, or
	rem while the handshake was running). rxChanMsg chains the rest.
	pl$ = chr$(10) : gosub sendFrame : rem cmd_sync_next_message
	print"{13}";pr$;
	goto mainLoop : rem without this, execution falls straight through
	rem into connect: below (this time NOT via gosub) and eventually
	rem hits its own RETURN with nothing on the stack to pop --
	rem "return without gosub".
	:
	:


connect:
#lineskip 500
	rem **handshake with the companion radio**
	rem app_start goes first, matching the official meshcore_py/meshcore-cli
	rem client (github.com/fdlamotte/meshcore_py) -- its connect() sends
	rem ONLY cmd_app_start, never cmd_device_query, making app_start the
	rem far more battle-tested/proven first command across real clients.
	pl$ = chr$(1)+chr$(0)+chr$(0)+chr$(0)+chr$(0)+chr$(0)+chr$(0)+chr$(0)+"C64"
	rem cmd_app_start: opcode, 7 reserved bytes, app name
	gosub sendFrame
	ws = 1 : gosub waitStage : rem wait for resp_code_self_info

	rem device_query still needed after app_start (not skipped like the
	rem reference client) -- it's what sets app_target_ver>=3 on the
	rem firmware side, which gates whether incoming channel messages use
	rem the v3 opcode (17) our parser understands, vs the legacy opcode
	rem (8) it doesn't.
	pl$ = chr$(22) + chr$(3) : rem cmd_device_query, app_ver=3
	gosub sendFrame
	ws = 2 : gosub waitStage : rem wait for resp_code_device_info

	pl$ = chr$(31) + chr$(0) : rem cmd_get_channel, channel_idx=0
	gosub sendFrame
	ws = 3 : gosub waitStage : rem wait for resp_code_channel_info

	pl$ = chr$(5) : rem cmd_get_device_time
	gosub sendFrame
	ws = 4 : gosub waitStage : rem wait for resp_code_curr_time
	return
	:
	:


waitStage:
#lineskip 500
	rem **retry loop: meshcore's binary framing has zero fault tolerance --**
	rem **a single byte lost anywhere in a multi-byte burst desyncs the**
	rem **whole frame (unlike meshtastic's newline-delimited text protocol,**
	rem **which self-resyncs every line). since these are idempotent**
	rem **request/response commands, just resend on failure and hope a**
	rem **later attempt gets through byte-perfect, instead of giving up**
	rem **after one shot.**
	rc = 0
	waitStageRetry:
	rem ~2.5s per attempt -- must comfortably exceed the ~1.4s it takes
	rem to transmit the largest reply (85 bytes) at 600 baud, or we'd
	rem resend before a reply could possibly have finished arriving.
	tw = ti + 150 : rem ti = 60 jiffies/sec
	waitStageLoop:
	gosub readFrame
	if hs >= ws then return
	if ti > tw then goto waitStageNextTry
	goto waitStageLoop
	waitStageNextTry:
	rc = rc + 1
	if rc >= 6 then return : rem give up after ~6 attempts, move on anyway
	gosub sendFrame : rem resend the same command (pl$ unchanged) and retry
	goto waitStageRetry
	:
	:


mainLoop:
#lineskip 500
	rem **main loop**
	gosub readFrame
	gosub printQueued
	gosub readKeyboard
	goto mainLoop
	:
	:


readFrame:
#lineskip 500
	rem **poll the machine-language engine.**
	rem it drains the whole rs-232 buffer and runs the
	rem '>' + len_lo + len_hi + payload state machine itself, setting
	rem READY when a complete frame is sitting in its buffer.
	rem   49152 ($c000) = entry     52992 ($cf00) = STATE
	rem   52993 ($cf01) = FLEN      52995 ($cf03) = READY
	rem   52736 ($ce00) = payload buffer
	sys 49152
	if peek(52995) = 0 then return : rem no complete frame yet
	fl = peek(52993) : rem payload length
	gosub handleFrame
	poke 52995,0 : rem release the buffer so ml can fill it again
	return
	:
	:


handleFrame:
#lineskip 500
	rem **dispatch a complete application frame by opcode (payload byte 0)**
	op = peek(52736) : rem BUF[0] = opcode
	if op = 13  then gosub rxDeviceInfo    : rem resp_code_device_info
	if op = 5   then gosub rxSelfInfo      : rem resp_code_self_info
	if op = 18  then gosub rxChannelInfo   : rem resp_code_channel_info
	if op = 9   then gosub rxCurrTime      : rem resp_code_curr_time
	if op = 17  then gosub rxChanMsg       : rem resp_code_channel_msg_recv_v3
	if op = 131 then gosub rxMsgWaiting    : rem push_code_msg_waiting (0x83)
	return
	:
	:


rxDeviceInfo:
#lineskip 500
	rem **resp_code_device_info - marks handshake stage 2 (sent 2nd now)**
	rem grab the radio's firmware version so we can show what we're
	rem paired with. layout: op,fw_ver_code,max_contacts/2,
	rem max_group_channels,ble_pin(4),build_date(12),manufacturer(40),
	rem fw_version(20 @ offset 60),repeat_en,path_hash_mode
	ez = 1 : eb = 52480 : ps = 60 : pe = 79 : gosub ext : fw$ = i$ : ez = 0
	hs = 2
	return
	:
	:


rxSelfInfo:
#lineskip 500
	rem **resp_code_self_info - grab our node name (offset 58..)**
	eb = 52480 : ps = 58 : pe = peek(52999) - 1 : gosub ext : nn$ = i$
	hs = 1
	return
	:
	:


rxChannelInfo:
#lineskip 500
	rem **resp_code_channel_info - cache this channel's name**
	rem layout: op, channel_idx, name(32, null-padded), secret(16)
	cv = peek(52737) : rem channel_idx at payload byte 1
	ez = 1 : eb = 52480 : ps = 2 : pe = 33 : gosub ext : ez = 0
	if cv < 40 then ch$(cv) = i$
	cw = 1 : rem tell chanScan that a reply landed
	rem only the FIRST reply (channel 0, during the handshake) advances
	rem the handshake stage. without this guard every reply from a later
	rem chanScan sweep would re-trigger stage 3 and confuse waitStage.
	if hs < 3 then cn$ = i$ : hs = 3 : rem i$, not o$ -- trimz/a2p are gone
	return
	:
	:


rxCurrTime:
#lineskip 500
	rem **resp_code_curr_time - remember device clock + our jiffy count**
	eb = 52736 : ps = 1 : pe = 4 : gosub ext : b4$ = i$ : gosub decU32
	bt = uv : bj = ti
	hs = 4
	return
	:
	:


rxChanMsg:
#lineskip 500
	rem **resp_code_channel_msg_recv_v3 - queue text for display**
	rem layout: op,snr,res1,res2,chan_idx,path_len,txt_type,ts(4),text
	rem text starts at 0-based offset 11
	rem every message already carries its channel index at payload byte
	rem 4, so filtering to the current channel costs one peek and no
	rem extra traffic at all.
	mc = peek(52740)
	rem **reject implausible frames before they can reach the archive.**
	rem an rs-232 overrun desyncs the frame parser - it locks onto a ">"
	rem sitting inside payload data, reads a plausible length after it and
	rem hands basic a "frame" assembled from random bytes. when byte 0 of
	rem that happens to be 17 it arrives here and gets archived, which is
	rem where the occasional line of garbage in scrollback came from: a
	rem byte ramp with utf-8 dots either side, clearly not a message.
	rem two cheap tests kill almost all of them. the firmware has 40 group
	rem channel slots, so an index above 39 cannot be real; and a channel
	rem message always carries at least one byte of text after its
	rem 11-byte header, so a length under 12 cannot be real either.
	if mc > 39 then rj = rj + 1 : return
	if fl < 12 then rj = rj + 1 : return
	rem **txt_type (payload byte 6) is the strongest of the three.** the
	rem firmware only ever sends 0 plain, 1 cli_data or 2 signed_plain, so
	rem a desynced frame passes this one byte only about 1 time in 64 --
	rem against roughly 1 in 6 for the channel index. all three together
	rem make a garbage frame reaching the archive very unlikely.
	rem this was worth finding precisely: a captured garbage line matched
	rem the radio's debug blob read from payload offset 18 while larch had
	rem asked for offset 11, i.e. the frame had landed in the buffer seven
	rem bytes early. that is a parser desync, not bad archive arithmetic.
	if peek(52742) > 2 then rj = rj + 1 : return
	rem bling on ANY incoming message, whatever channel it belongs to --
	rem this is "the mesh is talking", not "this is for you".
	poke 52998,0 : poke 52997,1
	rem cc = 255 is the "All" view: show every channel, filter nothing
	rem archive first, so every message is kept whatever channel we are
	rem watching -- this is what makes leaving a channel and coming back
	rem non-destructive.
	gosub larch
	if cc = 255 then goto rxChanMine
	if mc <> cc then goto rxChanOther
	rxChanMine:
	rem **our channel: extract, convert, queue. costs nothing extra.**
	rem deliberately identical to the pre-history build. a message for
	rem the channel we are watching is printed now and never replayed
	rem later -- replay only ever shows UNREAD messages, and by
	rem definition nothing on the current channel is unread. so it is
	rem never stored, and this path pays nothing for the history feature.
	eb = 52480 : ps = 11 : pe = peek(52999) - 1 : gosub ext
	rem in the "All" view, tag each line with the channel it arrived on --
	rem a merged feed without attribution is unreadable. only in All: on a
	rem named channel you already know where you are, and the prefix would
	rem eat 10 of the 40 columns for nothing.
	if cc <> 255 then goto rxChanQueue
	zn$ = ch$(mc)
	rem a channel we have never scanned has no name yet, so fall back to
	rem its index rather than showing empty brackets
	if zn$ = "" then zn$ = "ch" + mid$(str$(mc),2)
	i$ = "[" + left$(zn$,8) + "] " + i$
	rxChanQueue:
	rem no channel-name prefix here. the firmware already prepends
	rem "<sender>: " into the text itself -- basechatmesh.cpp's
	rem sendGroupMessage() does sprintf(&temp[5], "%s: ", sender_name)
	rem -- so the old cn$ + ": " + o$ printed "public: alice: hi".
	if im < 10 then im$(im) = i$ : im = im + 1
	goto rxChanDrain
	rxChanOther:
	rem **another channel: count it and keep a short copy for replay.**
	rem this is pure added work the old build skipped entirely, and it
	rem measurably cost loop rate, so two economies:
	rem  - only the first 40 characters (one screen line). the ext loop
	rem    dominates the per-message cost and scales with length, so a
	rem    150-char message would otherwise be ~4x the work.
	rem  - the text is ALREADY petscii, converted by the ml the moment
	rem    the frame landed, so storing and replaying are both cheap.
	rem    the previous build deferred a basic a2p to replay time, which
	rem    turned a channel switch with 4 unread into a ~10s freeze.
	eb = 52480 : ps = 11 : pe = peek(52999) - 1
	if pe > ps + 39 then pe = ps + 39
	gosub ext
	zs = ht - hz*int(ht/hz)
	hm$(zs) = i$ : hc(zs) = mc : ht = ht + 1
	rem refresh the prompt IN PLACE so the count is visible even when
	rem nothing prints: chr$(13) drops to column 0 of the next line and
	rem chr$(145) (cursor up) comes straight back, which rewrites the
	rem current line rather than scrolling a new prompt onto the screen.
	rem the counter only ever grows between redraws, so the prompt never
	rem shrinks and no stale characters are left behind.
	if mc < 40 then cu(mc) = cu(mc) + 1
	ut = ut + 1
	gosub setPrompt
	rem while a scrollback page is on screen, count the message but do
	rem NOT repaint -- the view belongs to the snapshot, not to us.
	if sb = 0 then print chr$(13);chr$(145);pr$;og$;
	rxChanDrain:
	rem **keep draining the radio's offline queue.**
	rem cmd_sync_next_message returns exactly ONE message, and the
	rem radio's queue is strict fifo (getFromOfflineQueue takes
	rem offline_queue[0], the OLDEST). we get one push_code_msg_waiting
	rem tickle per message, but a tickle is a 4-byte frame that gets
	rem swallowed whenever it lands while we're mid-frame or desynced.
	rem every missed tickle left one extra message stuck in the queue
	rem FOREVER, and since it's fifo we then always read a stale one --
	rem so the apparent delay grew and grew (minutes) and never
	rem recovered. so: after every message, immediately ask for the
	rem next one. when the queue really is empty the radio replies
	rem resp_code_no_more_messages (op 10), which we ignore, and the
	rem chain stops by itself.
	rem NOTE: this runs for filtered-out messages too -- that is why the
	rem "wrong channel" branch above jumps here instead of returning. the
	rem radio's offline queue is shared across ALL channels, so skipping
	rem the chain for another channel's message would strand it in the
	rem fifo and bring the growing-delay bug straight back.
	pl$ = chr$(10) : gosub sendFrame
	return
	:
	:


rxMsgWaiting:
#lineskip 500
	rem **push_code_msg_waiting - ask the radio for the queued message**
	pl$ = chr$(10) : rem cmd_sync_next_message
	gosub sendFrame
	return
	:
	:


printQueued:
#lineskip 500
	rem **print the next queued incoming message, if any**
	if im = 0 then return
	dq$ = im$(0)
	for i = 0 to im - 2 : im$(i) = im$(i+1) : next i
	im = im - 1
	rem **reuse the prompt's own row for the message.**
	rem the old form printed chr$(13) + message (whose PRINT adds its own
	rem newline) and then ANOTHER chr$(13) before the prompt, so a blank
	rem row was skipped every single time. instead: back up over
	rem "prompt + whatever is typed", write the message in that space,
	rem pad out anything left over from the longer prompt, then redraw
	rem the prompt underneath. messages flow, prompt stays at the bottom,
	rem no wasted rows. anything half-typed moves down with the prompt
	rem rather than being lost.
	rem back up to column 0 by reading the KERNAL's own cursor column
	rem ($d3/211) rather than assuming len(pr$)+len(og$). that assumption
	rem holds only while the prompt is the last thing printed, and it
	rem silently smears the message across the screen the moment anything
	rem else prints (the perf-instrumented build did exactly that). this
	rem form is self-correcting whatever touched the screen last.
	zl = peek(211) : if zl > 80 then zl = 80
	print left$(bk$,zl);dq$;
	if len(dq$) < zl then print left$(sp$,zl-len(dq$));
	print
	print pr$;og$;
	return
	:
	:


readKeyboard:
#lineskip 500
	rem **poll keyboard: typing / backspace / send / f1 / f7 / f3=debug**
	get a$ : if a$ = "" then return
	if a$ = chr$(13) then gosub sendChatMsg : og$ = "" : oa$ = "" : print"{13}";pr$; : return
	if a$ = chr$(20) then gosub deleteKey : return
	rem the function keys MUST be caught here, before the printable test
	rem below: f1/f3/f7 are chr$(133)/(134)/(136), which all fall inside
	rem the 32..218 "printable" range and would otherwise be appended to
	rem the typed line as garbage.
	if a$ = "{f1}" then gosub chanPicker : return
	if a$ = "{f5}" then gosub scrollBack : return
	if a$ = "{f7}" then cc = 0 : gosub setChan : return
	rem rj is the count of frames that arrived looking like channel
	rem messages but failed the plausibility tests -- i.e. the link is
	rem corrupting frames. it should be 0 on a healthy 600-baud link, and
	rem a climbing rj is the signature of a link running too fast: the
	rem messages are being dropped rather than displayed as garbage.
	if a$ = "{f3}" then print"{13}hs=";hs;" cc=";cc;" fl=";fl;" im=";im;" rj=";rj;"{13}nn=";nn$;" cn=";cn$;"{13}";pr$;og$; : return
	za = asc(a$) : if za < 32 or za > 218 then return : rem drop ctrl/colour/fn keys
	rem keep TWO copies of the typed line: og$ in petscii for the screen,
	rem oa$ in ascii for the wire. converting one character here costs a
	rem few ops and is invisible between keystrokes; the old code ran a
	rem whole p2a loop at send time instead, which froze for 1.74s on a
	rem 40-character message before a single byte went out.
	og$ = og$ + a$ : print a$;
	zc = za
	if za > 64 and za < 91 then zc = za + 32
	if za > 192 and za < 219 then zc = za - 128
	oa$ = oa$ + chr$(zc) : return
	:
	:


deleteKey:
#lineskip 500
	rem **backspace in the typed line**
	if og$ = "" then return
	og$ = left$(og$, len(og$)-1)
	oa$ = left$(oa$, len(oa$)-1) : rem keep the wire copy in step
	print chr$(20);
	return
	:
	:


sendChatMsg:
#lineskip 500
	rem **cmd_send_channel_txt_msg on the currently selected channel**
	if og$ = "" then return
	rem "All" is a read-only monitor: there is no single channel to send
	rem to, and quietly defaulting to Public would post to the wrong place.
	if cc = 255 then print"{13}pick a channel to send" : return
	uv = bt + int((ti - bj) / 60) : gosub encU32 : rem estimate device clock
	pl$ = chr$(3) + chr$(0) + chr$(cc) + e$ + oa$
	rem opcode, txt_type=plain, channel_idx=cc, timestamp(4), text
	poke 52998,5 : poke 52997,1 : rem all four leds, in unison
	gosub sendFrame
	rem **archive what we just sent.** the radio never echoes our own
	rem messages back to us, so without this the scrollback shows one
	rem side of the conversation -- you can read what everyone replied
	rem to and not what you said.
	rem staged into cbuf at exactly the offset an incoming frame carries
	rem its text (11), with clen set to match, so larch files it with no
	rem special case at all -- including the channel-prefixed copy that
	rem goes to the "All" region.
	rem "> " marks the line as ours, matching the prompt it was typed at
	rem and staying clearly distinct from an incoming "name: text".
	if ru = 0 then return
	ms$ = "> " + og$
	rem scrn renders at most two 40-column lines; cap the stored copy to
	rem match rather than letting it truncate somewhere arbitrary.
	if len(ms$) > 78 then ms$ = left$(ms$,78)
	for zq = 1 to len(ms$)
	poke 52491 + zq - 1, asc(mid$(ms$,zq,1))
	next zq
	poke 52999, 11 + len(ms$) : rem clen
	mc = cc : rem larch files under mc; for a send that is where we are
	gosub larch
	return
	:
	:


sendFrame:
#lineskip 500
	rem **wrap pl$ (opcode+payload) in transport framing and transmit**
	pn = len(pl$)
	u0 = pn - int(pn/256)*256 : u1 = int(pn/256)
	sf$ = chr$(60) + chr$(u0) + chr$(u1) + pl$ : rem 60 = '<'
	print#2, sf$; : rem trailing ";" - no auto cr appended
	rem (a ~200ms post-send settle used to live here, added while
	rem chasing what turned out to be the get#-eats-nulls bug. it
	rem wasn't the cause and it cost 0.2s on every single send --
	rem including the cmd_sync_next_message issued for each incoming
	rem message -- so it's gone.)
	return
	:
	:


encU32:
#lineskip 500
	rem **uv (0..4294967295) -> e$ (4 bytes, little-endian)**
	e0 = uv - int(uv/256)*256 : ev = int(uv/256)
	e1 = ev - int(ev/256)*256 : ev = int(ev/256)
	e2 = ev - int(ev/256)*256 : ev = int(ev/256)
	e3 = ev - int(ev/256)*256
	e$ = chr$(e0)+chr$(e1)+chr$(e2)+chr$(e3)
	return
	:
	:


decU32:
#lineskip 500
	rem **b4$ (4 bytes, little-endian) -> uv (0..4294967295)**
	uv = asc(mid$(b4$,1,1)) + asc(mid$(b4$,2,1))*256
	uv = uv + asc(mid$(b4$,3,1))*65536 + asc(mid$(b4$,4,1))*16777216
	return
	:
	:


ext:
#lineskip 500
	rem **build i$ from payload bytes ps..pe of the buffer at eb**
	rem eb = 52736 ($ce00) RAW bytes - opcodes, channel indexes, timestamps
	rem CLEN always equals fl now: the converter is strictly 1:1, because
	rem collapsing utf-8 here shifted every later offset and corrupted
	rem text that follows a binary field containing $e2.
	rem eb = 52480 ($cd00) TEXT - the ml has already converted ascii to
	rem petscii there. the old basic converter (a2p) cost ~56ms PER
	rem CHARACTER, i.e. 2.3s for a 40-char message, so it is gone from
	rem every text path.
	rem only the few short fields we actually parse get turned into
	rem strings (node name, channel name, timestamp, message text), so
	rem the string churn here is trivial next to the old approach of
	rem concatenating every single payload byte as it arrived.
	rem ez = 1 stops at the first null instead of building the whole
	rem fixed-width field and then scanning it. that pairs with the ml
	rem preserving 0 as 0, and replaces trimz entirely: a 32-byte channel
	rem name cost 0.45s to trim in basic on top of 0.67s to build.
	rem note zi is set to pe rather than jumping out of the loop -- an
	rem early exit from a FOR leaks a stack frame on this machine.
	i$ = ""
	if pe > fl - 1 then pe = fl - 1 : rem never read past the payload
	rem note: a c64 for-loop always runs its body at least once, even
	rem when the limit is below the start -- so guard empty ranges.
	if pe < ps then return
	for zi = ps to pe
	zb = peek(eb + zi)
	if zb = 0 and ez = 1 then zi = pe : goto extNext
	i$ = i$ + chr$(zb)
	extNext:
	next zi
	return
	:
	:


setPrompt:
#lineskip 500
	rem **build the input prompt from the current channel name.**
	rem the prompt doubles as the "which channel am i in" indicator.
	rem that is deliberate: a status bar on line 24 would be wiped by
	rem every screen scroll (the c64 scrolls all 25 lines) and would
	rem need repainting through screen ram to survive. the prompt is
	rem reprinted constantly anyway, so it costs nothing and scrolling
	rem can never corrupt it.
	rem 12 chars, not 8: "Emergency" truncated to "Emergenc>" reads like
	rem a bug rather than a deliberate cut. 12 + "> " still leaves most
	rem of the 40-column line for typing.
	pr$ = left$(cn$,12)
	rem **"+3" = 3 messages waiting on OTHER channels.**
	rem never the current channel: you are seeing its messages by virtue
	rem of being in it, and cu(cc) is cleared on entry so ut genuinely
	rem excludes it. the old form "Public(3)>" was correct but read as
	rem "Public has 3 unread", which is precisely the wrong impression --
	rem hence the "+", which says "3 more, elsewhere".
	rem str$ of a positive number carries a leading space, hence mid$.
	if ut > 0 then pr$ = pr$ + " +" + mid$(str$(ut),2)
	pr$ = pr$ + "> "
	return
	:
	:


setChan:
#lineskip 500
	rem **switch to channel cc (co = the channel we were on before)**
	rem cc = 255 is "All" and has no entry in ch$()
	if cc = 255 then cn$ = "All"
	if cc < 40 then cn$ = ch$(cc)
	rem only treat this as a real switch if the channel actually
	rem changed. cancelling out of the picker lands here too, and it
	rem must not eat messages that arrived while the picker was open.
	if cc = co then goto setChanBack
	rem anything still queued belongs to the channel we just left, so
	rem printing it under the new channel's name would be a lie.
	im = 0
	co = cc
	if ru = 1 then goto setChanReu
	rem no reu: the old behaviour - announce the channel and replay what
	rem arrived while we were away, out of the small ram ring.
	print"{13}-- ";cn$;" --"
	gosub replayChan
	goto setChanClr
	setChanReu:
	rem with an archive there is nothing to "replay": paint this channel's
	rem most recent page straight from the reu. leaving a channel and
	rem coming back is now non-destructive - you get the screen you left.
	gosub lreg
	if lf(zr) = 0 then print"{clear}{white}-- ";cn$;" --" : goto setChanClr
	zy = lw(zr) - 1 : if zy < 0 then zy = lr - 1
	gosub lpage
	gosub lhome
	setChanClr:
	rem entering a channel clears its unread count -- you have now seen
	rem those messages, because replayChan just printed them.
	rem in "All" nothing is unread elsewhere, and cu() has no slot 255
	if cc = 255 then ut = 0
	if cc < 40 then ut = ut - cu(cc) : cu(cc) = 0
	if ut < 0 then ut = 0
	setChanSame:
	rem prompt is built AFTER the counter clears, so it shows the new
	rem total rather than one that still includes this channel.
	gosub setPrompt
	print"{13}";pr$;og$;
	return
	:
	setChanBack:
	rem **same channel: the picker blanked the screen on its way out.**
	rem cancelling the picker, or re-picking the channel you are already
	rem on, lands here. chanPickEnd has already cleared the screen, so
	rem printing just the prompt left a bare screen that looked like the
	rem channel had lost its history -- it had not, and switching away
	rem and back repainted it, which is exactly how this was spotted.
	rem so put the page back here instead of relying on cc <> co.
	if ru = 1 then goto setChanBackReu
	print"{13}-- ";cn$;" --"
	goto setChanSame
	setChanBackReu:
	gosub lreg
	if lf(zr) = 0 then print"{clear}{white}-- ";cn$;" --" : goto setChanSame
	rem larch archives on receipt, so anything that arrived while the
	rem picker was open is already in the page we are about to paint.
	rem leaving the queue in place would print those same lines a second
	rem time underneath it.
	im = 0
	zy = lw(zr) - 1 : if zy < 0 then zy = lr - 1
	gosub lpage
	gosub lhome
	goto setChanSame
	:
	:


replayChan:
#lineskip 500
	rem **print the messages for cc that arrived while we were elsewhere**
	rem walk the ring oldest-first collecting this channel's entries,
	rem then print only the last cu(cc) of them -- exactly the number the
	rem picker and the prompt were showing.
	if cc = 255 then return : rem no per-channel replay in the All view
	if ht = 0 then return
	if cu(cc) = 0 then return
	rn = 0
	j0 = ht - hz : if j0 < 0 then j0 = 0
	for zj = j0 to ht - 1
	zs = zj - hz*int(zj/hz)
	if hc(zs) = cc and rn < 15 then rp(rn) = zs : rn = rn + 1
	next zj
	rem the ring may have rolled over and dropped some of what we
	rem counted, so never ask for more entries than we actually kept.
	rw = cu(cc) : if rw > rn then rw = rn
	if rw = 0 then return
	for zj = rn - rw to rn - 1
	print hm$(rp(zj))
	next zj
	rem the counter can promise more than the ring kept, or more than the
	rem burst cap of 15. say so rather than silently showing fewer --
	rem replaying 50 messages would take ~17s at 0.35s each, which is the
	rem freeze we just removed from channel switching.
	if cu(cc) > rw then print"...and ";mid$(str$(cu(cc)-rw),2);" more"
	return
	:
	:


chanScan:
#lineskip 500
	rem **ask the radio for channels 1..39 until we hit a run of blanks**
	rem getChannel() in src/helpers/BaseChatMesh.cpp returns true for
	rem EVERY index below max_group_channels (40 on this build) whether
	rem or not that slot was ever configured -- it just copies the slot
	rem out. so there is no "end of list" error to scan until, and an
	rem unused slot is only detectable by its name being blank.
	rem a full 0-39 sweep costs 40 x 58 bytes = ~39s at 600 baud, which
	rem is far too long to sit in front of. stop after 3 blanks in a
	rem row instead: the phone app hands out the lowest free slot, so
	rem real setups are contiguous from 0. typical cost ~4s.
	ce = 0 : cs = 1 : rem ch$(0) is already known from the handshake
	print"  ";left$(ch$(0),24)
	chanScanLoop:
	if cs > 39 then goto chanScanEnd
	rem cf = 1 means a full 0-39 sweep: ignore the blank-run shortcut.
	rem PROVEN NECESSARY: with channels at slots 0, 1 and 5, the
	rem stop-after-3-blanks scan quits at index 4 and never sees slot 5,
	rem so that channel is simply missing from the list. gaps are real
	rem (deleting a channel leaves one), hence the r key in the picker.
	if cf = 0 and ce > 2 then goto chanScanEnd
	sr = 0
	chanScanTry:
	cw = 0
	pl$ = chr$(31) + chr$(cs) : gosub sendFrame : rem cmd_get_channel
	rem **5s per attempt, and RETRY rather than abandoning the scan.**
	rem the reply itself is only 53 bytes (~0.9s), but on a busy mesh it
	rem queues behind the message backlog and logRxRaw floods -- and
	rem every message arriving mid-scan triggers another
	rem cmd_sync_next_message competing for the same wire. a single 3s
	rem timeout that aborted the whole scan meant one busy moment left
	rem the channel list stuck at just channel 0. measured: with traffic
	rem every 5s the old code failed on the very first request.
	tw = ti + 300
	chanScanWait:
	gosub readFrame : rem this is what actually collects the reply
	if cw = 1 and cv = cs then goto chanScanGot
	if ti > tw then goto chanScanRetry
	goto chanScanWait
	chanScanRetry:
	sr = sr + 1
	print".";  : rem so a slow scan doesn't look like a hang
	if sr < 3 then goto chanScanTry
	goto chanScanFail
	chanScanGot:
	if ch$(cs) = "" then ce = ce + 1 : goto chanScanNext
	ce = 0
	print"  ";left$(ch$(cs),24)
	chanScanNext:
	cs = cs + 1
	goto chanScanLoop
	chanScanEnd:
	ck = 1 : rem cached for the rest of the session -- f1 is instant now
	return
	chanScanFail:
	rem a request went unanswered. keep whatever names we did collect,
	rem but deliberately do NOT set ck: a half-finished scan must not
	rem be cached as authoritative, or one bad moment on the link would
	rem leave a short channel list stuck there for the whole session.
	rem the next f1 simply tries again.
	return
	:
	:


chanPicker:
#lineskip 500
	rem **f1 - show the channel list and pick one**
	rem *** MESSAGES KEEP ARRIVING BEHIND THIS SCREEN. we must NOT stop
	rem *** calling readFrame while it is up. at 600 baud the kernal's
	rem *** 256-byte rs-232 buffer fills in ~4 seconds, and an overrun
	rem *** does not merely lose bytes, it desyncs the frame parser --
	rem *** that is exactly the garbled-handshake failure seen in v23/v24.
	rem *** so "messages are paused" here means paused from the DISPLAY
	rem *** only: the ml engine and handleFrame run throughout, incoming
	rem *** messages queue up, and they print when we return.
	print"{clear}{white}Channels"
	print
	if ck = 1 then goto chanShow
	print"Scanning..."
	gosub chanScan
	chanShow:
	rem build the menu: map digits 0-9 onto whatever channel indexes
	rem actually have names, so a sparse setup still gets a dense menu.
	rem "All" is a synthetic entry, channel 255, always first
	pk(0) = 255 : np = 1
	for zi = 0 to 39
	if ch$(zi) <> "" and np < 10 then pk(np) = zi : np = np + 1
	next zi
	print"{clear}{white}Channels"
	print
	if np = 0 then print"None found" : goto chanPickLoop
	for zi = 0 to np - 1
	zt = pk(zi)
	print" ";chr$(48+zi);"  ";
	if zt = 255 then print"All";
	rem **basic has no short-circuit evaluation.** "if zt < 40 and
	rem cu(zt) > 0" reads cu(255) even when the first test is false, and
	rem cu() only goes to 39 -- bad subscript. the guard has to be a
	rem branch, not an AND.
	if zt > 39 then goto chanShowMark
	print left$(ch$(zt),18);
	rem unread count per channel -- this is where you actually look to
	rem see which channel has been busy while you were elsewhere.
	if cu(zt) > 0 then print" (";mid$(str$(cu(zt)),2);")";
	chanShowMark:
	if zt = cc then print" *";
	print
	next zi
	print
	print"0-";chr$(48+np-1);" Select   R Rescan   F1 Cancel"
	chanPickLoop:
	gosub readFrame : rem keep draining -- see the warning above
	get a$ : if a$ = "" then goto chanPickLoop
	if a$ = "{f1}" then goto chanPickEnd
	rem compare petscii codes, not literals: 82 = r, 210 = shift-r.
	za = asc(a$)
	if za = 82 or za = 210 then goto chanRescan
	if za < 48 or za > 57 then goto chanPickLoop
	zp = za - 48 : if zp >= np then goto chanPickLoop
	cc = pk(zp)
	goto chanPickEnd
	chanRescan:
	rem **r - sweep all 40 slots.** the quick scan stops after 3 blank
	rem slots in a row, which misses a channel sitting above a gap. this
	rem is the deliberate ~39s option for that case: names appear as they
	rem arrive, so you can pick yours the moment you see it.
	print"{clear}{white}Channels"
	print
	print"Scanning all 40 - about 40 seconds"
	print
	cf = 1 : gosub chanScan : cf = 0
	goto chanShow
	chanPickEnd:
	print"{clear}{white}"
	gosub setChan
	return
	:
	:


lreg:
#lineskip 500
	rem **which reu region belongs to the channel we are in**
	rem 0-7 have their own, higher channels share 7, "All" gets 8.
	zr = cc
	if zr > 7 then zr = 7
	if cc = 255 then zr = 8
	return
	:
	:


lxfer:
#lineskip 500
	rem **set up the REC for a zw-byte transfer, c64 zm <-> reu zo**
	rem the caller then pokes 144 (c64 -> reu) or 145 (reu -> c64).
	poke 57090, zm - 256*int(zm/256)
	poke 57091, int(zm/256)
	poke 57092, zo - 256*int(zo/256)
	poke 57093, int(zo/256) - 256*int(zo/65536)
	poke 57094, int(zo/65536)
	poke 57095, zw - 256*int(zw/256)
	poke 57096, int(zw/256)
	poke 57098, 0
	return
	:
	:


larch:
#lineskip 500
	rem **append this message to its channel's ring and to All**
	rem the ml turns the text into 1 or 2 screen-code lines at $cc00;
	rem soff tells it the text starts at payload byte 11 so the binary
	rem header is not converted.
	rem   49457 scrn   53000 SLEN (lines produced)   53001 SOFF
	if ru = 0 then return
	rem 1) this channel's own region: the text as it stands. no prefix --
	rem you already know which channel you are reading.
	poke 53001,11 : sys 49391
	zk = peek(53000)
	zr = mc : if zr > 7 then zr = 7
	gosub lput
	rem 2) the All region gets the SAME text with a channel prefix, so
	rem scrolling back through the merged feed still says where every
	rem line came from -- not just the live view.
	rem the prefix is poked into cbuf bytes 0-10, which hold the frame's
	rem binary header. that is safe: basic reads the opcode and channel
	rem index from the RAW buffer at 52736, never from cbuf. soff then
	rem moves back to cover the prefix, so the ml converts prefix+text as
	rem one string. "[" + 8 chars + "] " is exactly the 11 bytes free.
	zn$ = ch$(mc)
	if zn$ = "" then zn$ = "ch" + mid$(str$(mc),2)
	zg$ = "[" + left$(zn$,8) + "] "
	zh = 11 - len(zg$)
	for zq = 1 to len(zg$)
	poke 52480 + zh + zq - 1, asc(mid$(zg$,zq,1))
	next zq
	poke 53001,zh : sys 49391
	zk = peek(53000)
	zr = 8 : gosub lput
	return
	:
	:


lput:
#lineskip 500
	rem **write zk lines from $cc00 into region zr**
	rem one dma while the lines stay contiguous in the ring; at the wrap
	rem point, one line at a time.
	if lw(zr) + zk > lr then goto lputw
	zo = (zr * lr + lw(zr)) * 40
	zm = 52224 : zw = zk * 40
	gosub lxfer : poke 57089,144
	lw(zr) = lw(zr) + zk
	if lw(zr) >= lr then lw(zr) = 0
	if lf(zr) < lr then lf(zr) = lf(zr) + zk
	if lf(zr) > lr then lf(zr) = lr
	return
	lputw:
	for zq = 0 to zk - 1
	zo = (zr * lr + lw(zr)) * 40
	zm = 52224 + zq * 40 : zw = 40
	gosub lxfer : poke 57089,144
	lw(zr) = lw(zr) + 1
	if lw(zr) >= lr then lw(zr) = 0
	if lf(zr) < lr then lf(zr) = lf(zr) + 1
	next zq
	return
	:
	:


lpage:
#lineskip 500
	rem **paint region zr into rows 0-23, newest line zy at row 23**
	rem 24 lines, NOT 25: row 24 belongs to the input prompt. painting
	rem all 25 put the newest message on row 24 and the prompt then
	rem overwrote it the moment you started typing a reply.
	rem one dma of 1000 bytes when the range is contiguous and the ring
	rem is full, two when it crosses the wrap. no basic rendering - that
	rem is the whole reason lines are stored as screen codes.
	rem **only ever paint lines that have actually been written.** a
	rem region holding 5 lines used to get a full 25-line transfer, and
	rem the other 20 came back as uninitialised reu - a screenful of
	rem garbage characters.
	if ru = 0 then return
	zk = 24
	if lf(zr) < 24 then zk = lf(zr)
	if zk <= 0 then return
	if zk < 24 then print"{clear}{white}";
	zq = zy - zk + 1
	if zq < 0 then zq = zq + lr
	zx = zk
	if zq + zk <= lr then goto lpg1
	zx = lr - zq : rem split at the ring wrap
	lpg1:
	zo = (zr * lr + zq) * 40
	zm = 1024 + (24 - zk) * 40
	zw = zx * 40
	gosub lxfer : poke 57089,145
	if zx >= zk then return
	zo = zr * lr * 40
	zm = 1024 + (24 - zk + zx) * 40
	zw = (zk - zx) * 40
	gosub lxfer : poke 57089,145
	return
	:
	:


lhome:
#lineskip 500
	rem **cursor to the bottom line without scrolling or clearing**
	rem home, then 23 carriage returns. the caller's "{13}prompt" takes
	rem it to row 24. printing cr only moves the cursor, it does not
	rem erase, so the page we just dma'd stays intact.
	print"{home}";
	for zq = 1 to 23 : print : next zq
	return
	:
	:


scrollBack:
#lineskip 500
	rem **f5 - page back through this channel's archive**
	rem the archive is per channel, so paging needs no filtering: the
	rem lines are contiguous and a page is a single dma.
	if ru = 0 then return
	gosub lreg
	if lf(zr) = 0 then return
	sb = 1 : bo = peek(53280)
	zy = lw(zr) - 1 : if zy < 0 then zy = lr - 1
	sd = 0
	sbShow:
	gosub lpage
	poke 53280,2 : rem red border: you are looking at history
	gosub sbMark
	sbKey:
	rem keep draining the radio. same rule as the channel picker: at 600
	rem baud the kernal buffer fills in ~4s and an overrun desyncs the
	rem frame parser, so "paused" only ever means paused from the screen.
	gosub readFrame
	get a$ : if a$ = "" then goto sbKey
	if a$ = "{f5}" then goto sbOlder
	if a$ = "{f7}" then goto sbNewer
	goto sbExit
	sbOlder:
	rem stop at the oldest line the ring still holds
	if sd + 24 >= lf(zr) then goto sbKey
	sd = sd + 24
	zy = zy - 24 : if zy < 0 then zy = zy + lr
	goto sbShow
	sbNewer:
	if sd = 0 then goto sbKey
	sd = sd - 24
	if sd < 0 then sd = 0
	zy = zy + 24 : if zy >= lr then zy = zy - lr
	goto sbShow
	sbExit:
	rem back to the live view: the newest page of the same region
	zy = lw(zr) - 1 : if zy < 0 then zy = lr - 1
	gosub lpage
	poke 53280,bo
	sb = 0
	gosub lhome
	print"{13}";pr$;og$;
	return
	:
	:


sbMark:
#lineskip 500
	rem **show how far back we are, top right of the screen**
	rem poked straight into screen ram rather than printed, so it cannot
	rem scroll the snapshot we just loaded. screen codes: digits are
	rem 48-57, "-" is 45. colour ram is set too, in case that corner of
	rem the restored screen was never written.
	s1 = int(sd / 100) : s2 = int((sd - s1 * 100) / 10)
	s3 = sd - s1 * 100 - s2 * 10
	poke 1024+36,45 : poke 1024+37,48+s1
	poke 1024+38,48+s2 : poke 1024+39,48+s3
	poke 55296+36,1 : poke 55296+37,1
	poke 55296+38,1 : poke 55296+39,1
	return
	:
	:


reuDetect:
#lineskip 500
	rem **is a ram expansion unit present, and how big?**
	rem the 8726 REC lives at $df00-$df0a. this is deliberately in basic
	rem rather than machine code: it runs once at startup, costs a few
	rem hundred ms, and keeps the $c000 routine -- the one thing
	rem everything else depends on -- untouched.
	rem   57089 $df01 command: $90 = execute now, c64->reu
	rem                        $91 = execute now, reu->c64
	rem   57090/1 $df02/3 c64 address lo/hi
	rem   57092/3/4 $df04/5/6 reu address lo/hi/bank
	rem   57095/6 $df07/8 transfer length lo/hi
	rem   57098 $df0a address control (0 = increment both)
	rem the transfer does NOT autoload, so the base registers have to be
	rem written again before every transfer.
	ru = 0 : uk = 0
	rem test pattern in the cassette buffer at $033c (828) -- free ram
	poke 828,86 : poke 829,171 : poke 830,12 : poke 831,241
	ub = 0 : gosub reuStash
	rem wipe it, then pull it back. with no reu the registers are open
	rem bus, nothing is transferred, and the buffer stays wiped.
	poke 828,0 : poke 829,0 : poke 830,0 : poke 831,0
	ub = 0 : gosub reuFetch
	if peek(828) <> 86 then return
	if peek(829) <> 171 then return
	if peek(830) <> 12 then return
	if peek(831) <> 241 then return
	ru = 1 : uk = 64
	rem **size: find where the address space wraps.**
	rem bank 0 holds 86. write a different marker to bank 1, 2, 4, 8...
	rem and re-read bank 0. when bank 0 has changed, the bank register
	rem has wrapped and we know the real size.
	ub = 1
	reuSizeLoop:
	if ub > 128 then goto reuSizeDone
	rem marker is ub itself, NOT 200+ub: the probe reaches bank 128 on a
	rem large unit and 200+128 overflows a poke, which is an illegal
	rem quantity error at startup on anything 4mb or bigger. ub only ever
	rem takes the values 1,2,4..128, none of which collide with the 86
	rem written into bank 0, so it still distinguishes an alias.
	poke 828, ub
	gosub reuStash
	poke 828,0
	rem uc, not ub2: only the first TWO characters of a basic variable
	rem name are significant, so "ub2" IS "ub" and this would have zeroed
	rem the loop counter and hung.
	uc = ub : ub = 0 : gosub reuFetch : ub = uc
	if peek(828) <> 86 then goto reuSizeDone
	uk = ub * 64 * 2
	ub = ub * 2
	goto reuSizeLoop
	reuSizeDone:
	return
	:
	:


reuStash:
#lineskip 500
	rem **copy 1-4 bytes from $033c out to reu bank ub, offset 0**
	poke 57090,60 : poke 57091,3 : rem c64 $033c
	poke 57092,0 : poke 57093,0 : poke 57094,ub
	poke 57095,4 : poke 57096,0 : rem 4 bytes
	poke 57098,0
	poke 57089,144 : rem $90 execute now, c64 -> reu
	return
	:
	:


reuFetch:
#lineskip 500
	rem **copy those bytes back from reu bank ub, offset 0**
	poke 57090,60 : poke 57091,3
	poke 57092,0 : poke 57093,0 : poke 57094,ub
	poke 57095,4 : poke 57096,0
	poke 57098,0
	poke 57089,145 : rem $91 execute now, reu -> c64
	return
	:
	:


mldata:
#lineskip 500
	rem machine code for the $c000 serial engine
	data 173,3,207,208,110,172,156,2,204,155,2,240,102,177,247,238
	data 156,2,174,0,207,240,39,202,240,47,202,240,54,174,2,207
	data 157,0,206,238,2,207,232,236,1,207,144,217,32,164,192,169
	data 1,141,3,207,238,4,207,169,0,141,0,207,240,53,201,62
	data 208,195,169,1,141,0,207,208,188,141,1,207,169,2,141,0
	data 207,208,178,201,0,208,21,173,1,207,240,16,201,177,176,12
	data 169,0,141,2,207,169,3,141,0,207,208,153,169,0,141,0
	data 207,240,146,173,5,207,240,22,169,120,141,3,221,174,6,207
	data 189,152,192,201,255,240,8,141,1,221,232,142,6,207,96,169
	data 0,141,5,207,141,1,221,96,48,72,48,0,255,120,120,0
	data 120,120,0,255,162,0,160,0,236,1,207,176,54,189,0,206
	data 240,42,201,9,240,49,201,10,240,45,201,13,240,41,201,32
	data 144,41,201,127,176,37,201,65,144,18,201,91,144,12,201,97
	data 144,10,201,123,176,6,41,223,208,2,9,128,153,0,205,232
	data 200,208,197,140,7,207,96,169,32,208,241,169,46,208,237,174
	data 9,207,160,0,236,7,207,176,55,189,0,205,201,32,144,31
	data 201,64,144,29,201,96,144,13,201,128,144,14,201,192,144,17
	data 41,127,76,33,193,41,191,76,33,193,41,223,76,33,193,169
	data 32,153,0,204,232,200,192,80,144,202,169,2,141,8,207,96
	data 192,41,176,19,169,32,192,40,176,7,153,0,204,200,76,54
	data 193,169,1,141,8,207,96,169,32,192,80,176,7,153,0,204
	data 200,76,73,193,169,2,141,8,207,96

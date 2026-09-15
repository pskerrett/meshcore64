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
	rem 0.92b: handshake, channel list
	rem (f1) and per-channel chat. no
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
	open 2,2,3,chr$(7) : rem userport rs232 @ 600 baud
	rem **machine-language serial engine**
	rem basic needs ~50ms per received byte (get# alone benchmarks at
	rem 52ms), but at 600 baud a byte lands every 16.7ms -- a 3x deficit
	rem no amount of basic tuning can close. this 113-byte routine at
	rem $c000 drains the kernal buffer and assembles frames in ~50 cycles
	rem per byte instead, so basic only ever sees completed frames.
	for zi = 0 to 112 : read zd : poke 49152 + zi, zd : next zi
	get#2, rb$ : rem one arming call: the chkin that starts the receiver
	poke 52992,0 : poke 52995,0 : rem ml STATE=0, READY=0
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
	dim hm$(23) : dim hc(23) : dim rp(9)
	rem bk$ = cursor-lefts, sp$ = spaces. used to back up over the prompt
	rem and overwrite it, so an incoming message can reuse the prompt's
	rem own screen row instead of leaving it blank above every message.
	bk$ = "" : sp$ = ""
	for zi = 1 to 80 : bk$ = bk$ + chr$(157) : sp$ = sp$ + " " : next zi
	rem frame payload goes in a NUMERIC array, not a growing string.
	rem the old "fb$ = fb$ + chr$(rv)" allocated a brand-new string for
	rem every payload byte, littering basic's string heap until the
	rem garbage collector stalled everything for seconds at a time --
	rem that, not the baud rate or the mesh, is what made a short
	rem message take ~30s to appear. an array store costs nothing and
	rem creates no garbage. it also skips pointless work: device_info
	rem is 82 bytes we never even read.
	hs = 0 : im = 0 : og$ = "" : lt = ti
	cc = 0 : co = 0 : ck = 0 : ut = 0 : cf = 0 : ht = 0 : pr$ = "> " : rem channel, prev, cached, unread, sweep, history, prompt
	print"{lower}" : rem #lowercase only affects the compiler; this engages it on-screen
	print"{clear}{white}meshcore 64  0.92b"
	print"arming rs232 receiver..."
	tw = ti + 120 : rem ~2 second settle delay -- known c64 kernal rs232
	armWait: if ti < tw then goto armWait : rem quirk: bytes right after
	rem open can be lost/corrupted before the nmi-driven receiver is
	rem fully armed; give it a moment before trusting the link.
	print"connecting..."
	gosub connect
	print"{13}connected as ";nn$;" on ";cn$
	print"radio fw: ";fw$
	print"f1 channels   f7 public"
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
	ps = 60 : pe = 79 : gosub ext : gosub trimz : i$ = o$ : gosub a2p : fw$ = o$
	hs = 2
	return
	:
	:


rxSelfInfo:
#lineskip 500
	rem **resp_code_self_info - grab our node name (offset 58..)**
	ps = 58 : pe = fl - 1 : gosub ext : gosub a2p : nn$ = o$
	hs = 1
	return
	:
	:


rxChannelInfo:
#lineskip 500
	rem **resp_code_channel_info - cache this channel's name**
	rem layout: op, channel_idx, name(32, null-padded), secret(16)
	cv = peek(52737) : rem channel_idx at payload byte 1
	ps = 2 : pe = 33 : gosub ext : gosub trimz : i$ = o$ : gosub a2p
	if cv < 40 then ch$(cv) = o$
	cw = 1 : rem tell chanScan that a reply landed
	rem only the FIRST reply (channel 0, during the handshake) advances
	rem the handshake stage. without this guard every reply from a later
	rem chanScan sweep would re-trigger stage 3 and confuse waitStage.
	if hs < 3 then cn$ = o$ : hs = 3
	return
	:
	:


rxCurrTime:
#lineskip 500
	rem **resp_code_curr_time - remember device clock + our jiffy count**
	ps = 1 : pe = 4 : gosub ext : b4$ = i$ : gosub decU32
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
	if mc <> cc then goto rxChanOther
	rem **our channel: extract, convert, queue. costs nothing extra.**
	rem deliberately identical to the pre-history build. a message for
	rem the channel we are watching is printed now and never replayed
	rem later -- replay only ever shows UNREAD messages, and by
	rem definition nothing on the current channel is unread. so it is
	rem never stored, and this path pays nothing for the history feature.
	ps = 11 : pe = fl - 1 : gosub ext : gosub a2p
	rem no channel-name prefix here. the firmware already prepends
	rem "<sender>: " into the text itself -- basechatmesh.cpp's
	rem sendGroupMessage() does sprintf(&temp[5], "%s: ", sender_name)
	rem -- so the old cn$ + ": " + o$ printed "public: alice: hi".
	if im < 10 then im$(im) = o$ : im = im + 1
	goto rxChanDrain
	rxChanOther:
	rem **another channel: count it and keep a short copy for replay.**
	rem this is pure added work the old build skipped entirely, and it
	rem measurably cost loop rate, so two economies:
	rem  - only the first 40 characters (one screen line). the ext loop
	rem    dominates the per-message cost and scales with length, so a
	rem    150-char message would otherwise be ~4x the work.
	rem  - store the RAW text and run a2p at replay time. most stored
	rem    messages are never read back (the ring rolls over, or you
	rem    never visit that channel), so converting on arrival is work
	rem    thrown away.
	ps = 11 : pe = fl - 1
	if pe > ps + 39 then pe = ps + 39
	gosub ext
	zs = ht - 24*int(ht/24)
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
	print chr$(13);chr$(145);pr$;og$;
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
	if a$ = chr$(13) then gosub sendChatMsg : og$ = "" : print"{13}";pr$; : return
	if a$ = chr$(20) then gosub deleteKey : return
	rem the function keys MUST be caught here, before the printable test
	rem below: f1/f3/f7 are chr$(133)/(134)/(136), which all fall inside
	rem the 32..218 "printable" range and would otherwise be appended to
	rem the typed line as garbage.
	if a$ = "{f1}" then gosub chanPicker : return
	if a$ = "{f7}" then cc = 0 : gosub setChan : return
	if a$ = "{f3}" then print"{13}hs=";hs;" cc=";cc;" fl=";fl;" im=";im;"{13}nn=";nn$;" cn=";cn$;"{13}";pr$;og$; : return
	za = asc(a$) : if za < 32 or za > 218 then return : rem drop ctrl/colour/fn keys
	og$ = og$ + a$ : print a$; : return
	:
	:


deleteKey:
#lineskip 500
	rem **backspace in the typed line**
	if og$ = "" then return
	og$ = left$(og$, len(og$)-1)
	print chr$(20);
	return
	:
	:


sendChatMsg:
#lineskip 500
	rem **cmd_send_channel_txt_msg on the currently selected channel**
	if og$ = "" then return
	uv = bt + int((ti - bj) / 60) : gosub encU32 : rem estimate device clock
	i$ = og$ : gosub p2a
	pl$ = chr$(3) + chr$(0) + chr$(cc) + e$ + o$
	rem opcode, txt_type=plain, channel_idx=cc, timestamp(4), text
	gosub sendFrame
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
	rem **build i$ from frame payload bytes fb(ps) .. fb(pe)**
	rem only the few short fields we actually parse get turned into
	rem strings (node name, channel name, timestamp, message text), so
	rem the string churn here is trivial next to the old approach of
	rem concatenating every single payload byte as it arrived.
	i$ = ""
	if pe > fl - 1 then pe = fl - 1 : rem never read past the payload
	rem note: a c64 for-loop always runs its body at least once, even
	rem when the limit is below the start -- so guard empty ranges.
	if pe < ps then return
	for zi = ps to pe
	i$ = i$ + chr$(peek(52736 + zi))
	next zi
	return
	:
	:


a2p:
#lineskip 500
	rem **wire ascii -> screen petscii, i$ -> o$**
	o$ = ""
	rem guard the empty string: a c64 for-loop always runs its body at
	rem least once, so len(i$)=0 would evaluate mid$(i$,1,1) = "" and
	rem then asc("") -> ?illegal quantity error. empty strings reach
	rem here now that unconfigured channel slots (all-null names) get
	rem trimmed to "" by trimz.
	if i$ = "" then return
	for zi = 1 to len(i$)
	rem default to '.' so control codes never reach the screen: petscii
	rem colour codes (5, 28-31, 144-159) and other controls would
	rem otherwise be printed literally and repaint the display.
	z$ = mid$(i$,zi,1) : za = asc(z$) : zc$ = "."
	if za > 31 and za < 127 then zc$ = z$
	if za > 64 and za < 91 then zc$ = chr$(za+128)
	if za > 96 and za < 123 then zc$ = chr$(za-32)
	o$ = o$ + zc$
	next zi
	return
	:
	:


p2a:
#lineskip 500
	rem **screen petscii -> wire ascii, i$ -> o$**
	o$ = ""
	if i$ = "" then return : rem see the note in a2p
	for zi = 1 to len(i$)
	z$ = mid$(i$,zi,1) : za = asc(z$) : zc$ = z$
	if za > 64 and za < 91 then zc$ = chr$(za+32)
	if za > 192 and za < 219 then zc$ = chr$(za-128)
	o$ = o$ + zc$
	next zi
	return
	:
	:


trimz:
#lineskip 500
	rem **truncate i$ at its first chr$(0), result -> o$**
	rem note: never RETURN from inside the FOR loop below -- doing so
	rem leaks a for/next stack frame every call (classic c64 basic
	rem gotcha: the shared gosub/for-next stack only reclaims a loop's
	rem frame when its NEXT actually runs to completion), which
	rem eventually corrupts the stack and crashes with an unrelated
	rem "return without gosub" error elsewhere.
	tz = 0 : rem tz = 1-based index of first chr$(0), 0 = not found
	for zi = 1 to len(i$)
	if mid$(i$,zi,1) = chr$(0) and tz = 0 then tz = zi
	next zi
	if tz = 0 then o$ = i$ : return
	o$ = left$(i$,tz-1)
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
	cn$ = ch$(cc)
	rem only treat this as a real switch if the channel actually
	rem changed. cancelling out of the picker lands here too, and it
	rem must not eat messages that arrived while the picker was open.
	if cc = co then goto setChanSame
	rem anything still queued belongs to the channel we just left, so
	rem printing it under the new channel's name would be a lie.
	im = 0
	co = cc
	print"{13}-- ";cn$;" --"
	gosub replayChan : rem show what arrived while we were away
	rem entering a channel clears its unread count -- you have now seen
	rem those messages, because replayChan just printed them.
	ut = ut - cu(cc)
	if ut < 0 then ut = 0
	cu(cc) = 0
	setChanSame:
	rem prompt is built AFTER the counter clears, so it shows the new
	rem total rather than one that still includes this channel.
	gosub setPrompt
	print"{13}";pr$;og$;
	return
	:
	:


replayChan:
#lineskip 500
	rem **print the messages for cc that arrived while we were elsewhere**
	rem walk the ring oldest-first collecting this channel's entries,
	rem then print only the last cu(cc) of them -- exactly the number the
	rem picker and the prompt were showing.
	if ht = 0 then return
	if cu(cc) = 0 then return
	rn = 0
	j0 = ht - 24 : if j0 < 0 then j0 = 0
	for zj = j0 to ht - 1
	zs = zj - 24*int(zj/24)
	if hc(zs) = cc and rn < 10 then rp(rn) = zs : rn = rn + 1
	next zj
	rem the ring may have rolled over and dropped some of what we
	rem counted, so never ask for more entries than we actually kept.
	rw = cu(cc) : if rw > rn then rw = rn
	if rw = 0 then return
	for zj = rn - rw to rn - 1
	i$ = hm$(rp(zj)) : gosub a2p : print o$
	next zj
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
	print"{clear}{white}channels"
	print
	if ck = 1 then goto chanShow
	print"scanning..."
	gosub chanScan
	chanShow:
	rem build the menu: map digits 0-9 onto whatever channel indexes
	rem actually have names, so a sparse setup still gets a dense menu.
	np = 0
	for zi = 0 to 39
	if ch$(zi) <> "" and np < 10 then pk(np) = zi : np = np + 1
	next zi
	print"{clear}{white}channels"
	print
	if np = 0 then print"none found" : goto chanPickLoop
	for zi = 0 to np - 1
	print" ";chr$(48+zi);"  ";left$(ch$(pk(zi)),18);
	rem unread count per channel -- this is where you actually look to
	rem see which channel has been busy while you were elsewhere.
	if cu(pk(zi)) > 0 then print" (";mid$(str$(cu(pk(zi))),2);")";
	if pk(zi) = cc then print" *";
	print
	next zi
	print
	print"0-";chr$(48+np-1);" select   r all   f1 cancel"
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
	print"{clear}{white}channels"
	print
	print"scanning all 40 - about 40 seconds"
	print
	cf = 1 : gosub chanScan : cf = 0
	goto chanShow
	chanPickEnd:
	print"{clear}{white}"
	gosub setChan
	return
	:
	:


mldata:
#lineskip 500
	rem machine code for the $c000 serial engine
	data 173,3,207,208,107,172,156,2,204,155,2,240,99,177,247,238
	data 156,2,174,0,207,240,36,202,240,44,202,240,51,174,2,207
	data 157,0,206,238,2,207,232,236,1,207,144,217,169,1,141,3
	data 207,238,4,207,169,0,141,0,207,240,53,201,62,208,198,169
	data 1,141,0,207,208,191,141,1,207,169,2,141,0,207,208,181
	data 201,0,208,21,173,1,207,240,16,201,177,176,12,169,0,141
	data 2,207,169,3,141,0,207,208,156,169,0,141,0,207,240,149
	data 96

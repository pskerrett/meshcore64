#!/usr/bin/env python3
"""
Fake MeshCore companion radio, speaking the real binary serial protocol,
so meshcore64.bas can be tested in VICE without the actual hardware.

Frame layouts are taken from examples/companion_radio/MyMesh.cpp and
cross-checked against fdlamotte/meshcore_py's reader.py.

Host -> device frames start with '<' (0x3C); device -> host with '>' (0x3E);
both carry a 2-byte little-endian length. Note the length MSB is always
0x00 for real frames (max 176 bytes) -- that zero byte is exactly what
the C64's GET# used to swallow.
"""
import socket, struct, sys, time, threading, signal
import os as _os

# Flush the log on SIGTERM: the test runner kills us when VICE exits, and
# the default SIGTERM handler would skip the finally block entirely.
signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))

HOST, PORT = "127.0.0.1", 25232

# --- command opcodes (host -> device) ---
CMD_APP_START            = 1
CMD_SEND_CHANNEL_TXT_MSG = 3
CMD_GET_DEVICE_TIME      = 5
CMD_SYNC_NEXT_MESSAGE    = 10
CMD_DEVICE_QUERY         = 22
CMD_GET_CHANNEL          = 31

# --- response / push codes (device -> host) ---
RESP_OK                = 0
RESP_SELF_INFO         = 5
RESP_CURR_TIME         = 9
RESP_NO_MORE_MESSAGES  = 10
RESP_DEVICE_INFO       = 13
RESP_CHANNEL_MSG_V3    = 17
RESP_CONTACT_MSG_V3    = 16
RESP_CHANNEL_INFO      = 18
PUSH_MSG_WAITING       = 0x83
PUSH_LOG_RX_DATA       = 0x88

def pad(s: bytes, n: int) -> bytes:
    """Fixed-width, NUL-padded - the source of all those null bytes."""
    return s[:n] + b"\x00" * max(0, n - len(s))

def device_info() -> bytes:
    p = bytearray()
    p += bytes([RESP_DEVICE_INFO, 13, 175, 40])       # op, fw_ver, contacts/2, channels
    p += struct.pack("<I", 0)                          # ble_pin  -> 4 nulls
    p += pad(b"15 Sep 2026", 12)                       # build_date
    p += pad(b"Heltec V3", 40)                         # manufacturer -> ~31 nulls
    p += pad(b"v1.0.0-local-0679db", 20)               # fw_version
    p += bytes([0, 0])                                 # repeat_enabled, path_hash_mode
    assert len(p) == 82, len(p)
    return bytes(p)

def self_info() -> bytes:
    p = bytearray()
    p += bytes([RESP_SELF_INFO, 1, 22, 22])
    p += bytes(range(32))                              # pubkey (contains 0x00!)
    p += struct.pack("<i", 0) + struct.pack("<i", 0)   # lat, lon -> 8 nulls
    p += bytes([0, 0, 0, 0])                           # multi_acks, loc_policy, telem, manual
    p += struct.pack("<I", 869525) + struct.pack("<I", 62500)
    p += bytes([7, 5])                                 # sf, cr
    p += b"59800697"                                   # node name at offset 58
    assert len(p) == 66, len(p)
    return bytes(p)

# Configured channel slots. Everything else in 0..39 exists but is blank --
# this mirrors getChannel() in BaseChatMesh.cpp, which returns true for ANY
# index < MAX_GROUP_CHANNELS whether or not that slot was ever set up. So
# there is no "end of list" error; an unused slot is only detectable by its
# name being empty.
MAX_GROUP_CHANNELS = 40
# Overridable so the harness can test a SPARSE layout (gaps between
# configured slots), which is the assumption the client's early-stop scan
# rests on.  MC64_CHANNELS="0:Public,1:Test,5:Emergency"
import os
CHANNELS = {0: b"Public", 1: b"Test", 2: b"Emergency"}
if os.environ.get("MC64_CHANNELS"):
    CHANNELS = {}
    for _e in os.environ["MC64_CHANNELS"].split(","):
        _i, _n = _e.split(":")
        CHANNELS[int(_i)] = _n.encode()

def channel_info(idx: int) -> bytes:
    p = bytearray()
    p += bytes([RESP_CHANNEL_INFO, idx])
    p += pad(CHANNELS.get(idx, b""), 32)               # name at offset 2
    p += pad(b"\x01\x02\x03" if idx in CHANNELS else b"", 16)   # secret
    assert len(p) == 50, len(p)
    return bytes(p)

RADIO_START = time.time()
RADIO_T0 = 1715770351 if _os.environ.get("MC64_RADIOCLK") == "2024" else None   # MC64_RADIOCLK=2024: the radio's clock after a power-up (15 May 2024)


def curr_time() -> bytes:
    if RADIO_T0 is not None:
        return bytes([RESP_CURR_TIME]) + struct.pack("<I", int(RADIO_T0 + time.time() - RADIO_START))
    return bytes([RESP_CURR_TIME]) + struct.pack("<I", int(time.time()))

def chan_msg(text: bytes, chan: int = 0) -> bytes:
    p = bytearray()
    # op,snr,res,res,chan_idx,path_len,txt_type -- chan_idx is byte 4
    p += bytes([RESP_CHANNEL_MSG_V3, 20, 0, 0, chan, 255, 0])
    p += struct.pack("<I", int(time.time()))
    # the firmware prepends "<sender>: " into the text itself
    # (BaseChatMesh::sendGroupMessage), so the client must NOT add its own
    p += text                                                 # text at offset 11
    return bytes(p)

def dm_msg(text: bytes, contact_n: int = 1) -> bytes:
    """
    A DIRECT message -- RESP_CODE_CONTACT_MSG_RECV_V3, opcode 16.

    This harness only ever produced channel messages, which is precisely
    why the client could ship with opcode 16 unhandled: nothing here could
    provoke it. An unhandled opcode does not re-issue SYNC_NEXT_MESSAGE,
    so one DM wedged the radio's queue and every message behind it -- of
    any kind -- was stranded.

      [16][snr][0][0][key:6][path_len][txt_type][timestamp:4][text]

    The key must match CMD_GET_CONTACTS, or the client cannot name the
    sender.
    """
    key = bytes([(contact_n + 1) * 7 + i for i in range(6)])
    p = bytearray()
    p += bytes([RESP_CONTACT_MSG_V3, 20, 0, 0])
    p += key
    p += bytes([255, 0])                       # path_len, TXT_TYPE_PLAIN
    p += struct.pack("<I", int(time.time()))
    p += text
    return bytes(p)


def wrap(payload: bytes) -> bytes:
    return b"\x3e" + struct.pack("<H", len(payload)) + payload

def contact_frame(code, key, typ, name, hops=b""):
    f = bytearray([code]) + key + bytes([typ, 0, len(hops) if hops else 0xFF])
    f += hops + bytes(64 - len(hops))
    f += name + bytes(32 - len(name)) + struct.pack("<I", 0) * 4
    return bytes(f)


def adv_key(n):
    return bytes([(n * 13 + i) & 0xFF for i in range(32)])


class Radio:
    def __init__(self, conn):
        self.conn = conn
        self.buf = bytearray()
        self.queue = []          # pending messages, FIFO like the firmware
        self.sched = []          # (due time, frame, label) pushed later
        self.log = []

    def run_sched(self):
        now = time.time()
        due = [x for x in self.sched if x[0] <= now]
        self.sched = [x for x in self.sched if x[0] > now]
        for _, frame, what in due:
            self.conn.sendall(wrap(frame))
            self.log.append(f"  -> {what}")

    def advert_push(self, step):
        """Nodes the radio hears. 1: brand new repeater (full record, 0x8A);
        2: a node the radio has but the client does not (key only, 0x80);
        3: a node the client already has (0x80, must NOT be fetched);
        4: another brand new one, a companion."""
        if step == 1:
            self.conn.sendall(wrap(contact_frame(0x8A, adv_key(1), 2, b"Brand New Repeater Alpha", b"\x21")))
            self.log.append("  -> NEW_ADVERT Brand New Repeater Alpha (repeater)")
        elif step == 2:
            self.conn.sendall(wrap(bytes([0x80]) + adv_key(2)))
            self.log.append("  -> ADVERT (key only) late room server")
        elif step == 3:
            known = bytes([((0 + 1) * 7 + i) & 0xFF for i in range(32)])   # first listed contact
            self.conn.sendall(wrap(bytes([0x80]) + known))
            self.log.append("  -> ADVERT (key only) a node the client has")
        elif step == 4:
            self.conn.sendall(wrap(contact_frame(0x8A, adv_key(4), 1, b"Fresh Companion Gamma")))
            self.log.append("  -> NEW_ADVERT Fresh Companion Gamma (companion)")

    def req_reply(self, push, body, blank=False):
        """Login / telemetry, as the radio answers them. MC64_LOGIN:
        ok (default) | fail (0x86) | silent (sent by flood, then nothing: a
        wrong password, or out of range) | dead (sent DIRECT, silent, until
        the route is reset, then it floods and works) | err (ERR_NOT_FOUND)."""
        mode = os.environ.get("MC64_LOGIN", "ok")
        # guest: needs a prior login (a blank one will do); pwonly: blank
        # logins are ignored, so only a real password gets on the list
        if mode in ("guest", "pwonly"):
            if push == 0x85:
                if mode == "pwonly" and blank:
                    mode = "silent"
                else:
                    self.logged = True
                    mode = "ok"
            else:
                mode = "ok" if getattr(self, "logged", False) else "silent"
        if mode == "err":
            self.send(bytes([1, 2]))
            return
        direct = mode == "dead" and not getattr(self, "path_reset", False)
        sent = bytes([6, 0 if direct else 1]) + struct.pack("<II", 7, 4000)
        self.send(sent)
        if mode == "silent" or direct:
            self.log.append("   [no answer from the node]")
        elif mode == "fail" and push == 0x85:
            self.send(bytes([0x86, 0]) + body[1:7])
        else:
            self.send(bytes([push]) + body)

    def send(self, payload):
        self.conn.sendall(wrap(payload))
        self.log.append(f"  -> {payload[0]} ({len(payload)}B)")

    def push_dm(self, text, contact_n=1):
        """Queue a DIRECT message and tickle, like queueMessage()."""
        self.queue.append(dm_msg(text, contact_n))
        self.conn.sendall(wrap(bytes([PUSH_MSG_WAITING])))
        self.log.append(f"  -> TICKLE DM (queue={len(self.queue)})")

    def push_message(self, text, chan=0):
        """Queue a message and tickle, exactly like onChannelMessageRecv()."""
        self.queue.append(chan_msg(text, chan))
        self.conn.sendall(wrap(bytes([PUSH_MSG_WAITING])))
        self.log.append(f"  -> TICKLE ch{chan} (queue={len(self.queue)})")

    def feed(self, data):
        self.buf += data
        while True:
            i = self.buf.find(b"\x3c")
            if i < 0:
                self.buf.clear(); return
            if len(self.buf) < i + 3:
                return
            ln = struct.unpack("<H", self.buf[i+1:i+3])[0]
            if len(self.buf) < i + 3 + ln:
                return
            payload = bytes(self.buf[i+3:i+3+ln])
            del self.buf[:i+3+ln]
            self.handle(payload)

    def check_dup(self, sig):
        """
        Stand in for the real mesh's duplicate filter.

        The firmware hashes the timestamp into each packet -- "mostly an
        extra blob to help make packet_hash unique" -- and every repeater
        drops a hash it has already seen (SimpleMeshTables::wasSeen). So a
        message that is byte-identical to an earlier one NEVER REACHES
        ANYONE. It is not visible from the C64 side at all: the radio
        still answers OK, and the client happily shows it in the local
        scrollback while the mesh silently discards it.

        That is exactly what a hardcoded timestamp of zero produced, and
        nothing here would have caught it. Now it is loud.
        """
        if not hasattr(self, "_seen"):
            self._seen = set()
        ts = sig[-1]
        if ts == 0:
            self.log.append("   *** TIMESTAMP IS ZERO -- "
                            "the mesh would drop this as a duplicate ***")
        if sig in self._seen:
            self.log.append("   *** DUPLICATE PACKET -- "
                            "every repeater would drop this ***")
        self._seen.add(sig)

    def handle(self, p):
        if not p:
            return
        op = p[0]
        self.log.append(f"<- cmd {op} ({len(p)}B)")
        if op == CMD_APP_START:
            self.send(self_info())
        elif op == CMD_DEVICE_QUERY:
            self.send(device_info())
        elif op == CMD_GET_CHANNEL:
            idx = p[1] if len(p) > 1 else 0
            nm = CHANNELS.get(idx, b"").decode() or "(empty)"
            self.log.append(f"   [GET_CHANNEL {idx} -> {nm}]")
            self.send(channel_info(idx))
        elif op == 4:   # CMD_GET_CONTACTS
            if not hasattr(self, "list_at"):
                self.list_at = getattr(self, "nsync", 0)
            # (name, ADV_TYPE): 1 chat, 2 repeater, 3 room, 4 sensor
            contacts = [(b"repeater-north", 2), (b"alice", 1), (b"bob-mobile", 1),
                        (b"room-server", 3), (b"hilltop-relay", 2), (b"carol", 1),
                        (b"dave", 1), (b"warehouse-gw", 4), (b"eve-portable", 1),
                        (b"frank", 1), (b"south-bridge", 2), (b"grace", 1),
                        (b"heidi", 1), (b"tower-east", 2), (b"ivan", 1),
                        (b"judy", 1), (b"depot-node", 2), (b"mallory", 1)]
            # MC64_LONGNAMES=1: names up to the 31-character limit
            if os.environ.get("MC64_LONGNAMES"):
                contacts[0] = (b"ORD-MPRVL-GRNVL-RPTR-NORTH-0001", 2)   # 31
                contacts[4] = (b"Ghostrider Tophat Repeat", 2)          # 24
                contacts[10] = (b"McHazelwood G2 Repeater", 2)          # 23
                contacts[1] = (b"Devonshire Companion Node", 1)         # 25
            # MC64_NCONTACTS: a big mesh, to exercise the table limits
            extra = int(os.environ.get("MC64_NCONTACTS", "0"))
            for k in range(extra):
                contacts.append((b"node%03d" % k, 1 + k % 3))
            # Our firmware: optional byte 5 filters by type (0 = all).
            # MC64_NOFILTER=1 behaves like stock firmware, which ignores it.
            want = p[5] if len(p) >= 6 and not os.environ.get("MC64_NOFILTER") else 0
            self.log.append(f"   [GET_CONTACTS len={len(p)} filter={want}]")
            self.send(bytes([2]) + struct.pack("<I", len(contacts)))
            removed = getattr(self, "removed", set())
            ages = os.environ.get("MC64_AGES")      # purge test: some nodes old, some favourites
            now_t = struct.unpack('<I', curr_time()[1:5])[0]
            for n, (nm, typ) in enumerate(contacts):
                if n in removed:
                    continue
                if want and typ != want:
                    continue
                f = bytearray()
                f.append(3)                       # RESP_CODE_CONTACT
                f += bytes([((n + 1) * 7 + i) & 0xFF for i in range(32)])   # pub key
                f.append(typ)                     # type
                f.append(1 if ages and n % 7 == 3 else 0)   # flags (bit 0 = favourite)
                # first contact floods (no route), the rest have 2-3 hops
                if n == 0:
                    f.append(0xFF)
                    f += bytes(64)
                else:
                    hops = bytes([(0x10 + n) & 0xFF, (0x20 + n) & 0xFF, (0x30 + n) & 0xFF])[:1 + n % 3]
                    f.append(len(hops))
                    f += hops + bytes(64 - len(hops))
                f += nm + bytes(32 - len(nm))     # name
                if ages:
                    old = n % 3 == 0
                    t_adv = now_t - (90 if old else 1) * 86400
                    t_mod = now_t - (90 if old and n % 9 != 0 else 1) * 86400   # every 3rd old one was touched lately
                    f += struct.pack("<I", t_adv) + struct.pack("<I", 0) * 2 + struct.pack("<I", t_mod)
                else:
                    f += struct.pack("<I", 0) * 4     # advert ts, lat, lon, lastmod
                self.send(bytes(f))
                self.log.append(f"  -> CONTACT {nm.decode()} type {typ}")
            self.send(bytes([4]) + bytes(4))      # END_OF_CONTACTS
            self.log.append("  -> END_OF_CONTACTS")
        elif op == 15:  # CMD_REMOVE_CONTACT
            k = bytes(p[1:33])
            hit = [n for n in range(5000) if bytes([((n + 1) * 7 + i) & 0xFF for i in range(32)]) == k]
            self.removed = getattr(self, "removed", set())
            self.nrm = getattr(self, "nrm", 0) + 1
            if hit and not (os.environ.get("MC64_RMFAIL") and self.nrm % 5 == 0):
                self.removed.add(hit[0])
                self.log.append(f"   [REMOVE_CONTACT #{hit[0]} ok]")
                self.send(bytes([0]))
            else:
                self.log.append(f"   [REMOVE_CONTACT {k[:4].hex()} refused]")
                self.send(bytes([1, 2]))
        elif op == 30:  # CMD_GET_CONTACT_BY_KEY
            k = p[1:33]
            self.log.append(f"   [GET_CONTACT_BY_KEY {k[:4].hex()}]")
            if k == adv_key(2):
                self.send(contact_frame(3, k, 3, b"Late Room Server Beta", b"\x44\x45"))
            else:
                self.send(bytes([1, 2]))
        elif op == 7:   # CMD_SEND_SELF_ADVERT
            kind = "flood" if len(p) >= 2 and p[1] == 1 else "zero-hop"
            self.log.append(f"   [ADVERT {kind}]")
            self.send(bytes([0]))
        elif op == 20:  # CMD_GET_BATT_AND_STORAGE
            self.send(bytes([12]) + struct.pack("<H", 4012)
                      + struct.pack("<I", 1840) + struct.pack("<I", 7936))
            self.log.append("  -> BATT 4012mv, 1840/7936 kb")
        elif op == 13:  # CMD_RESET_PATH
            self.log.append("   [C64 WIPED ROUTE -> will flood]")
            self.path_reset = True
            self.send(bytes([0]))
        elif op == 2:   # CMD_SEND_TXT_MSG (direct message)
            txt = p[13:].decode("ascii", "replace")
            ts = struct.unpack("<I", p[3:7])[0]
            self.log.append(f"   [C64 DM to {p[7:13].hex()}: {txt!r} ts={ts}]")
            self.check_dup(("dm", p[7:13], txt, ts))
            tag = bytes([0xA0 + (ts & 15), 0xB1, 0xC2, 0xD3])
            self.send(bytes([6, 0]) + tag + struct.pack("<I", 4000))
            if os.environ.get("MC64_ACK", "1") == "1":
                self.sched.append((time.time() + float(os.environ.get("MC64_ACKAT", "4")),
                                   bytes([0x82]) + tag + struct.pack("<I", 1234), "SEND_CONFIRMED"))
        elif op == CMD_GET_DEVICE_TIME:
            self.send(curr_time())
        elif op == 6:   # CMD_SET_DEVICE_TIME
            global RADIO_T0, RADIO_START
            secs = struct.unpack("<I", p[1:5])[0]
            self.log.append(f"   [SET_DEVICE_TIME {secs} ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(secs))})]")
            RADIO_T0, RADIO_START = secs, time.time()
            self.send(bytes([RESP_OK]))
        elif op == CMD_SYNC_NEXT_MESSAGE:
            self.nsync = getattr(self, "nsync", 0) + 1
            # MC64_ADVERT_FROM=list: count from the first list fetch
            _f = os.environ.get("MC64_ADVERT_FROM", "3")
            if _f == "list":
                _f = getattr(self, "list_at", None)
                _f = 10 ** 9 if _f is None else _f + 3
            _f = int(_f)
            if os.environ.get("MC64_ADVERT") and self.nsync in (_f, _f + 3, _f + 6, _f + 9):
                self.advert_push((self.nsync - _f) // 3 + 1)
            if self.queue:
                self.send(self.queue.pop(0))     # FIFO, oldest first
            else:
                self.send(bytes([RESP_NO_MORE_MESSAGES]))
        elif op == CMD_SEND_CHANNEL_TXT_MSG:
            self.send(bytes([RESP_OK]))
            ch = p[2]                       # channel_idx is payload byte 2
            ts = struct.unpack("<I", p[3:7])[0]
            txt = p[7:].decode("ascii", "replace")
            nm = CHANNELS.get(ch, b"?").decode()
            self.log.append(
                f"   [C64 SENT on ch{ch} ({nm}): {txt!r} ts={ts}]")
            self.check_dup(("ch", ch, txt, ts))
            # MC64_ECHO=n: n repeaters re-broadcast it, 2 s apart. The raw
            # packet is a flood group text, one hop so far; the payload is
            # hash, mac, ciphertext padded to 16 -- as long as ours must be.
            n_echo = int(os.environ.get("MC64_ECHO", "0"))
            if n_echo:
                name = b"59800697"
                plen = 3 + 16 * ((5 + len(name) + 2 + len(p[7:]) + 15) // 16)
                sig = bytes([0x4C, ts & 255, (ts >> 8) & 255]) + bytes(plen - 3)
                for k in range(n_echo):
                    raw = bytes([0x15, 1 + (k % 2)]) + bytes([0x11 + k] * (1 + (k % 2))) + sig
                    self.sched.append((time.time() + float(os.environ.get("MC64_ECHOAT", "2")) + 2 * k,
                                       bytes([PUSH_LOG_RX_DATA, 20, 200]) + raw, f"ECHO {k + 1}"))
        elif op == 26:  # CMD_SEND_LOGIN
            self.log.append(f"   [LOGIN to {p[1:5].hex()} pw={p[33:].decode('ascii','replace')!r}]")
            self.req_reply(0x85, bytes([1]) + p[1:7], blank=(len(p) <= 33 or p[33] == 0))
        elif op == 39:  # CMD_SEND_TELEMETRY_REQ
            # Cayenne LPP: channel, type, value big-endian. A battery, a
            # temperature, a humidity and a below-zero temperature, so the
            # sign path gets exercised too.
            lpp = bytes([1, 116]) + struct.pack(">H", 412)
            lpp += bytes([2, 103]) + struct.pack(">h", 215)
            lpp += bytes([3, 104]) + bytes([94])
            lpp += bytes([4, 103]) + struct.pack(">h", -55)
            self.log.append(f"   [TELEMETRY -> {lpp.hex()}]")
            self.req_reply(0x8B, bytes([0]) + p[4:10] + lpp)
        elif op == 8:   # CMD_SET_ADVERT_NAME
            self.log.append(f"   [NODE NAME -> {p[1:].decode('ascii','replace')!r}]")
            self.send(bytes([0]))
        elif op == 11:  # CMD_SET_RADIO_PARAMS
            fr, bw = struct.unpack("<II", p[1:9])
            self.log.append(f"   [RADIO {fr}kHz bw={bw}Hz sf={p[9]} cr={p[10]}]")
            self.send(bytes([0]))
        elif op == 12:  # CMD_SET_RADIO_TX_POWER
            self.log.append(f"   [TX POWER -> {p[1]} dBm]")
            self.send(bytes([0]))
        elif op == 32:  # CMD_SET_CHANNEL
            idx = p[1]
            nm = p[2:34].split(b"\0")[0]
            sec = p[34:50]
            if nm:
                CHANNELS[idx] = nm
                self.log.append(f"   [SET_CHANNEL {idx} -> {nm.decode()!r} key={sec.hex()}]")
            else:
                CHANNELS.pop(idx, None)
                self.log.append(f"   [SET_CHANNEL {idx} -> removed]")
            self.send(bytes([0]))
        else:
            self.log.append(f"   (unhandled cmd {op})")

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"fake radio listening on {HOST}:{PORT}", flush=True)
    conn, _ = srv.accept()
    print("VICE connected", flush=True)
    r = Radio(conn)
    # backlog: three messages already queued before the client connects
    if os.environ.get("MC64_CHAT"):          # a believable backlog from the same script
        for _t in ("alice: Morning all, who is on the mesh today?", "bob-mobile: Up on the ridge, 3 hops to the city",
                   "carol: Copy, solid here too"):
            r.queue.append(chan_msg(_t.encode(), 0))
        r.queue.append(dm_msg(b"alice: Hey, got a minute to test the new relay?", 1))
    else:
        r.queue.append(chan_msg(b"bob: backlog A", 0))
        r.queue.append(dm_msg(b"backlog DM from alice", 1))
        for i in ("backlog B", "backlog C"):
            r.queue.append(chan_msg(b"bob: " + i.encode(), 0))
    conn.settimeout(0.2)
    start = time.time()
    next_msg = start + 15.0
    next_log = start + 8.0
    n = 0
    try:
        while time.time() - start < 400:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                r.feed(data)
            except socket.timeout:
                pass
            r.run_sched()
            if time.time() > next_log:
                # a ~60-byte raw packet dump, like a real mesh overhearing traffic
                blob = bytes([PUSH_LOG_RX_DATA, 20, 200]) + bytes(range(60))
                r.conn.sendall(wrap(blob))
                r.log.append("  -> LOG_RX_DATA (63B)")
                next_log = time.time() + 3.0
            # MC64_MSGMAX: go quiet after this many messages. the blank-screen
            # test has to tell "the client repainted the page" apart from "a
            # new message happened to print on that row", so the mesh must be
            # silent while the screen is being measured.
            if time.time() > next_msg and n >= int(os.environ.get("MC64_MSGMAX", "999999")):
                next_msg = time.time() + 3600
            if time.time() > next_msg:
                n += 1
                # alternate short and near-max-length messages
                # rotate across channels so the client's filtering is
                # actually exercised: only ch0 traffic should be displayed
                # while the client sits in Public.
                _keys = sorted(CHANNELS)
                ch = _keys[n % len(_keys)]
                # every 3rd message carries the punctuation a phone
                # keyboard actually produces: curly apostrophe (U+2019,
                # e2 80 99), curly quotes, and an em dash.
                # MC64_CHAT=file: "channel|sender: text" per line, played in order
                # (channel = index, or "dm" for a direct message), then repeated.
                if os.environ.get("MC64_CHAT"):
                    _lines = [l.rstrip("\n") for l in open(os.environ["MC64_CHAT"], encoding="utf-8") if "|" in l and not l.startswith("#")]
                    _c, _t = _lines[(n - 1) % len(_lines)].split("|", 1)
                    if _c == "dm":
                        r.push_dm(_t.encode("utf-8"), 1)
                    else:
                        r.push_message(_t.encode("utf-8"), int(_c))
                    next_msg = time.time() + float(os.environ.get("MC64_MSGINT", "10"))
                    continue
                if n % 3 == 0 and not os.environ.get("MC64_LONGMSG"):
                    _bad = 200 if os.environ.get("MC64_BADFRAME") else ch
                    r.push_message("dave: it\u2019s \u201cfine\u201d \u2014 ok?".encode("utf-8"), _bad)
                    next_msg = time.time() + float(os.environ.get("MC64_MSGINT", "10"))
                    continue
                who = (b"alice", b"bob", b"carol")[n % 3]
                # MC64_BADFRAME: hand the client a frame that looks like a
                # channel message but carries a channel index no firmware
                # could produce. That is what a desynced frame parser hands
                # BASIC after an RS-232 overrun, and it used to get archived
                # and painted as a line of garbage in scrollback.
                if os.environ.get("MC64_BADFRAME"):
                    r.push_message(who + b": hello %d" % n, 200)
                elif os.environ.get("MC64_LONGMSG"):
                    # MC64_LONGMSG: near the 160-char limit, four screen lines
                    r.push_message(who + b": hello %d " % n + b"the quick brown fox jumps over the lazy dog " * 3 + b"END%d" % n, ch)
                else:
                    r.push_message(who + b": hello %d" % n, ch)
                next_msg = time.time() + float(os.environ.get("MC64_MSGINT", "10"))
    except KeyboardInterrupt:
        print("(terminated)", flush=True)
    except Exception as e:
        print("err:", e, flush=True)
    finally:
        print("\n".join(r.log), flush=True)
        print(f"queue left: {len(r.queue)}", flush=True)

main()

"""Meridian Foods: a fictional 1,200-person food distributor.

Every record here is invented. Ticket ages are stored as minutes before "now"
so the service level states are meaningful the moment the database is created:
one incident already past target, one about to go, and a spread behind them.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from . import policy
from .clock import Clock
from .models import (
    Article,
    CatalogItem,
    Change,
    Event,
    MatrixCell,
    Message,
    Problem,
    Release,
    SlaRuleRow,
    Team,
    Technician,
    Ticket,
)

TEAMS = [
    ("service_desk", "Service desk", "First line. Accounts, how-do-I, anything not yet understood", 1,
     "password reset, account unlock, how-do-i, triage, software request, general question"),
    ("endpoint", "Endpoint", "Laptops, phones, printers, peripherals, software installs", 2,
     "laptop, desktop, printer, label printer, monitor, dock, mobile phone, os build, software install"),
    ("network", "Network", "Connectivity, VPN, depot wifi, switches, the floor scanners", 3,
     "vpn, wifi, access point, switch, firewall, dns, barcode scanner, depot link, cabling"),
    ("erp_apps", "ERP and applications", "ERP, warehouse management, reporting, integrations", 4,
     "erp, invoicing, warehouse management, reporting, month end, batch job, integration, api, database"),
    ("identity", "Identity and security", "Access grants, joiners and leavers, phishing", 5,
     "access request, permissions, joiner, leaver, mfa, phishing, malware, mailbox, shared drive"),
    ("facilities", "Facilities", "Badges, desks, rooms, the physical building", 6,
     "badge, door reader, desk move, meeting room, av, lighting, building"),
]

# id, name, team, tier, skills, capacity, location, on leave
#
# Two people on a team are never interchangeable, which is the whole reason
# "who on this team" is worth a judgment rather than a counter. Every skill
# word here is also a word a ticket might use.
TECHS = [
    ("ja", "J. Alvarez", "service_desk", "Team lead", "triage, escalation, how-do-i, account unlock", 6, "HQ, Utrecht", False),
    ("kb", "K. Boateng", "service_desk", "First line", "password reset, account unlock, how-do-i, software request", 10, "HQ, Utrecht", False),
    ("nsv", "N. Silva", "service_desk", "First line", "how-do-i, mobile phone, software request, general question", 10, "HQ, Utrecht", False),
    ("tk", "T. Okafor", "service_desk", "First line", "triage, password reset, general question", 10, "Rotterdam depot", True),

    ("sd", "S. Devi", "endpoint", "First line", "laptop, os build, software install, monitor, dock", 9, "HQ, Utrecht", False),
    ("hn", "H. Nakamura", "endpoint", "Second line", "label printer, barcode scanner hardware, printer, depot kit", 8, "Rotterdam depot", False),
    ("pv", "P. Varga", "endpoint", "Second line", "laptop, encryption, firmware, os build, hardware fault", 8, "HQ, Utrecht", False),
    ("dm", "D. Mbeki", "endpoint", "First line", "monitor, dock, peripheral, mobile phone, desk setup", 10, "Field", False),

    ("ao", "A. Okonkwo", "network", "Second line", "wifi, access point, depot link, barcode scanner, cabling", 8, "Rotterdam depot", False),
    ("yt", "Y. Tanaka", "network", "Third line", "switch, firewall, dns, routing, core network", 6, "HQ, Utrecht", False),
    ("cm", "C. Moreau", "network", "Second line", "vpn, remote access, field connectivity, dns", 8, "Field", False),

    ("lc", "L. Chen", "erp_apps", "Third line", "erp, invoicing, batch job, payments gateway, integration", 6, "HQ, Utrecht", False),
    ("fr", "F. Rossi", "erp_apps", "Second line", "reporting, month end, export, dashboard, cold chain", 8, "HQ, Utrecht", False),
    ("ga", "G. Adeyemi", "erp_apps", "Second line", "warehouse management, stock count, picking, scanner app", 8, "Rotterdam depot", False),
    ("bl", "B. Lindqvist", "erp_apps", "Third line", "database, performance, api, integration, data fix", 6, "HQ, Utrecht", False),

    ("mf", "M. Farah", "identity", "Second line", "phishing, malware, mailbox, security incident, mfa", 8, "HQ, Utrecht", False),
    ("en", "E. Novak", "identity", "Second line", "joiner, leaver, access request, permissions, shared drive", 9, "HQ, Utrecht", False),
    ("wh", "W. Haddad", "identity", "Third line", "privileged access, audit, compliance, certificates", 6, "HQ, Utrecht", False),

    ("rp", "R. Patel", "facilities", "First line", "badge, door reader, desk move, meeting room", 10, "HQ, Utrecht", False),
    ("od", "O. Dlamini", "facilities", "Second line", "av, meeting room, lighting, building works", 8, "Rotterdam depot", False),
]

# id, subject, requester, dept, impact, urgency, category, team, assignee,
# status, age_minutes, major, hold_reason, problem_id, service, ci
TICKETS = [
    ("INC-4416", "ERP invoice batch failed overnight, 812 invoices unsent",
     "Tomas Vinter", "Finance, Rotterdam", "department", "critical", "ERP / Invoicing",
     "erp_apps", None, "new", 265, True, "", "PRB-118", "Invoice dispatch", "erp-prod-01, pay-gw-02"),
    ("INC-4417", "Warehouse scanners dropping off wifi in Bay 3",
     "Priya Raghavan", "Warehouse Ops", "team", "critical", "Network / Wireless",
     "network", "ao", "in_progress", 476, True, "", "PRB-114", "Depot wifi", "ap-rtm-b3"),
    ("INC-4404", "Phishing email reported by six people in Accounts",
     "Dana Reiss", "Finance", "department", "high", "Security / Phishing",
     "identity", "mf", "in_progress", 460, False, "", "", "Mail filtering", "mx-edge-01"),
    ("REQ-2205", "Offboard warehouse supervisor, revoke all access today",
     "Hannah Groves", "People Ops", "team", "high", "Identity / Leaver",
     "identity", "mf", "assigned", 345, False, "", "", "Offboarding", ""),
    ("INC-4409", "Cold-chain dashboard showing stale temperatures",
     "Ines Oyelaran", "Quality", "department", "medium", "ERP / Reporting",
     "erp_apps", "ao", "in_progress", 288, False, "", "", "Cold chain", "erp-prod-01"),
    ("INC-4401", "VPN drops every twenty minutes for field sales",
     "Owen Brett", "Sales", "team", "high", "Network / VPN",
     "network", "lc", "in_progress", 140, False, "", "", "Remote access", "vpn-gw-02"),
    ("INC-4395", "Reporting module times out on month-end export",
     "Tomas Vinter", "Finance", "department", "medium", "ERP / Reporting",
     "erp_apps", None, "new", 120, False, "", "PRB-109", "Reporting", "erp-prod-01"),
    ("INC-4398", "Label printer in Bay 1 printing blank labels",
     "Kofi Mensah", "Warehouse Ops", "team", "medium", "Endpoint / Printing",
     "endpoint", "sd", "in_progress", 1080, False, "", "", "Label printing", "prn-rtm-b1"),
    ("REQ-2210", "New depot hire needs ERP and scanner access by Monday",
     "Hannah Groves", "People Ops", "individual", "high", "Identity / Joiner",
     "identity", "lc", "assigned", 300, False, "", "", "New starter", ""),
    ("INC-4390", "Shared drive permissions wrong after the reorg",
     "Elena Duarte", "HR", "team", "medium", "Identity / Access",
     "identity", None, "new", 400, False, "", "", "File shares", "fs-hq-02"),
    ("REQ-2201", "Badge access for the new Rotterdam depot",
     "Nadia Kerr", "Facilities", "individual", "medium", "Facilities / Access",
     "facilities", "rp", "assigned", 500, False, "", "", "Badge access", ""),
    ("INC-4412", "Finance laptop will not wake from sleep",
     "Marc Albo", "Finance", "individual", "low", "Endpoint / Hardware",
     "endpoint", "sd", "on_hold", 600, False,
     "Waiting on the caller for a photo of the asset tag", "", "End user compute", "lap-fin-118"),
    ("REQ-2208", "Additional monitor for the Rotterdam sales desk",
     "Jesper Holt", "Sales", "individual", "low", "Endpoint / Peripheral",
     "endpoint", None, "new", 700, False, "", "", "Peripherals", ""),
    ("INC-4386", "Meeting room display not connecting to laptops",
     "Sam Ihejirika", "Facilities", "individual", "low", "Facilities / AV",
     "facilities", "rp", "on_hold", 900, False,
     "Waiting on the AV vendor to quote a replacement", "", "Meeting rooms", "av-hq-3f"),

    # Four tickets that are already on the desk twice over, written the way
    # different people actually write them. None of them repeats the wording of
    # what it duplicates, which is the whole difficulty: two people describing
    # one fault reach for different nouns, and shared-word matching is looking
    # for the nouns.
    ("INC-4421", "Pickers in the back aisles keep having to walk to the front to get a signal",
     "Dmitri Sokolov", "Warehouse Ops", "team", "high", "Network / Wireless",
     "network", None, "new", 90, False, "", "", "Depot wifi", ""),
    ("INC-4422", "Handhelds losing connection mid-pick, we are running well behind",
     "Grace Mutua", "Warehouse Ops", "team", "high", "Network / Wireless",
     "network", None, "new", 55, False, "", "", "Depot wifi", ""),
    ("INC-4423", "None of the invoices went out again overnight, same as last quarter",
     "Bea Lindholm", "Finance", "department", "high", "ERP / Invoicing",
     "erp_apps", None, "new", 40, False, "", "", "Invoice dispatch", "erp-prod-01"),
    ("INC-4424", "Label printer in Bay 1 printing blank labels",
     "Kofi Mensah", "Warehouse Ops", "team", "medium", "Endpoint / Printing",
     "endpoint", None, "new", 25, False, "", "", "Label printing", "prn-rtm-b1"),
]

CONVERSATION = [
    ("INC-4416", 0, "Tomas Vinter", "public",
     "The overnight invoice run did not go out. Finance has 812 invoices sitting in the "
     "queue from yesterday and not one of them reached a customer. Month end is Friday so "
     "we cannot sit on these. The job log shows a timeout against the payments gateway "
     "around 02:40, but I do not have access to restart it.", "", ""),
    ("INC-4416", 48, "L. Chen", "internal",
     "Gateway certificate rotated on Tuesday night, same signature as INC-4207 in March. "
     "Not an ERP fault. The payments team has to re-pin it, then the batch replays from the "
     "admin console. Worth attaching to PRB-118.", "", ""),
    ("INC-4416", 51, "Relay", "draft",
     "Hi Tomas, thanks for flagging this. The failure came from a certificate rotation on "
     "the payments gateway rather than the ERP itself. We are re-pinning the certificate now "
     "and expect the batch to replay within the hour, well ahead of Friday. I will confirm "
     "here as soon as all 812 invoices have gone out.",
     "needs_review", "it promises a restart time that no target or runbook commits to"),
    ("INC-4417", 0, "Priya Raghavan", "public",
     "Three of the six handhelds in Bay 3 keep dropping off the wifi mid-pick. They "
     "reconnect if you walk to the aisle end. Picking is running about forty minutes behind.",
     "", ""),

    # The rest exist so sentiment has something to read. A desk where every
    # ticket is one plainly worded sentence reads neutral all day, which is
    # true and useless; real queues have people chasing, people being patient,
    # and the occasional thank-you.
    ("INC-4398", 0, "Kofi Mensah", "public",
     "Label printer in Bay 1 is printing blank labels again. Same as last month.", "", ""),
    ("INC-4398", 540, "Kofi Mensah", "public",
     "Any update on this? We are hand-writing labels for the afternoon run and it is costing "
     "us about an hour a pallet.", "", ""),
    ("INC-4398", 1010, "Kofi Mensah", "public",
     "This is the third time I have chased. Nobody has been down to look at it and the depot "
     "manager is now asking me why we are behind. I need someone here today, not another "
     "reference number.", "", ""),

    ("INC-4412", 0, "Marc Albo", "public",
     "My laptop will not wake from sleep. I have to hold the power button every morning.", "", ""),
    ("INC-4412", 240, "S. Devi", "public",
     "Hi Marc — could you send a photo of the asset tag on the underside so I can pull the "
     "right model? Then I can check whether the firmware update applies.", "", ""),
    ("INC-4412", 300, "Marc Albo", "public",
     "Sure, will do when I am back at my desk. No great rush, it is only a nuisance first "
     "thing. Thanks for picking it up.", "", ""),

    ("INC-4386", 0, "Sam Ihejirika", "public",
     "The 3rd floor meeting room display will not connect to any laptop. We have moved two "
     "client calls to the ground floor this week.", "", ""),
    ("INC-4386", 620, "Sam Ihejirika", "public",
     "It has been three weeks. I appreciate you are waiting on the vendor, but from where I "
     "sit the room has simply not worked all month and nobody tells us anything unless I ask. "
     "Can someone give me a date I can actually plan around?", "", ""),

    ("REQ-2208", 0, "Jesper Holt", "public",
     "Could I get a second monitor for the Rotterdam sales desk when you have a moment? "
     "Absolutely no rush — whenever one comes free is fine. Thanks very much.", "", ""),

    ("REQ-2201", 0, "Nadia Kerr", "public",
     "Badge access needed for the new Rotterdam depot for the three starters on my list.", "", ""),
    ("REQ-2201", 420, "R. Patel", "public",
     "All three are on the depot reader now, and I added them to the goods-in door as well "
     "since they will need it from Monday.", "", ""),
    ("REQ-2201", 455, "Nadia Kerr", "public",
     "That is brilliant, thank you — and thank you for thinking of goods-in, I had not even "
     "asked. You have saved me a job on Monday morning.", "", ""),

    ("INC-4390", 0, "Elena Duarte", "public",
     "Shared drive permissions are wrong after the reorg. Half of HR can see the old "
     "structure and the other half cannot see anything.", "", ""),
    ("INC-4390", 380, "Elena Duarte", "public",
     "Still the same today. I know the reorg made a mess of this so I am not blaming anyone, "
     "but is there an estimate? We have appraisals starting Thursday.", "", ""),

    ("INC-4421", 0, "Dmitri Sokolov", "public",
     "Anyone picking in the back half of the warehouse has to walk up to the front before the "
     "scanner will talk to anything. It has been like this all morning.", "", ""),
    ("INC-4422", 0, "Grace Mutua", "public",
     "Scanners drop out every few minutes and we lose the pick. Three of us are affected and the "
     "afternoon run is going to be late.", "", ""),
    ("INC-4423", 0, "Bea Lindholm", "public",
     "The overnight invoice job produced nothing again. I gather this happened before and it was "
     "something to do with a certificate.", "", ""),
    ("INC-4424", 0, "Kofi Mensah", "public",
     "Raising this again because the last one has gone quiet. Bay 1 label printer, still blank "
     "labels.", "", ""),
]

PROBLEMS = [
    ("PRB-118", "Payments gateway breaks whenever its certificate rotates", "Known error",
     "First seen in March",
     "The gateway pins a certificate that the platform team rotates quarterly, and the two "
     "calendars have never been connected.",
     "Re-pin by hand, then replay the batch. Roughly forty minutes.", "CHG-0291", "L. Chen", "crit"),
    ("PRB-114", "Bay 3 loses wifi coverage under full racking", "Digging",
     "Six reports in 60 days",
     "Suspected: the access point went in before the racking was raised, and stock height "
     "now blocks it. A survey is booked.",
     "Scanners fall back to Bay 2 coverage at the aisle end, which slows picking.",
     "CHG-0288", "A. Okonkwo", "hot"),
    ("PRB-109", "Month-end reporting exports time out", "Digging",
     "Three month ends running", "",
     "Finance splits the export by depot and stitches it together in a spreadsheet.",
     "", "Nobody", "warn"),
]

CHANGES = [
    ("CHG-0286", "Patch warehouse switch firmware", "ok", "06:00 to 07:00", 0, "Mon", 21, "", False, False, "REL-0041"),
    ("CHG-0291", "Coordinate gateway certificate rotation", "crit", "22:00 to 02:00", 1, "Tue", 22,
     "Collides with CHG-0293 on pay-gw-02", True, False, "REL-0042"),
    ("CHG-0287", "Add depot printer to the Rotterdam queue", "mute", "any time", 1, "Tue", 22, "", False, False, ""),
    ("CHG-0293", "Payments gateway minor version bump", "hot", "23:00 to 01:00", 2, "Wed", 23,
     "Collides with CHG-0291 on pay-gw-02", True, False, "REL-0042"),
    ("CHG-0288", "Install the Bay 3 access point", "hot", "05:00 to 08:00", 3, "Thu", 24, "", False, False, "REL-0041"),
    ("CHG-0284", "ERP quarterly index rebuild", "hot", "01:00 to 05:00", 5, "Sat", 26, "", False, False, "REL-0042"),
    ("CHG-0295", "Decommission the old badge reader", "ok", "any time", 6, "Sun", 27, "", False, False, ""),
]

RELEASES = [
    ("REL-0042", "ERP 24.3 quarterly", "4 October, 01:00 to 06:00", 2, "hot", "L. Chen",
     "Carries the payments gateway re-pin, so PRB-118 closes with it."),
    ("REL-0041", "Depot network refresh, phase 2", "24 September, 05:00 to 08:00", 3, "ok", "A. Okonkwo",
     "Bay 3 access point plus switch firmware. Closes PRB-114 if the survey holds."),
    ("REL-0040", "Scanner firmware 9.2", "Shipped 12 September", 5, "ok", "S. Devi",
     "Went out clean. Scanner drop-offs fell but did not stop, which is what opened PRB-114."),
]

ARTICLES = [
    ("KB-0031", "Barcode scanner keeps losing the warehouse wifi",
     "Re-pair to WH-FLOOR and clear the saved profiles. Works about four times in five.",
     "A. Okonkwo", "Checked 3 weeks ago", False, 41, "Live", "scanner wifi bay barcode depot"),
    ("KB-0007", "Reset your own password from your phone",
     "About a minute with your phone. No ticket needed.",
     "M. Farah", "Checked 2 months ago", False, 38, "Live", "password login locked access reset"),
    ("KB-0018", "Laptop will not wake from sleep",
     "Hold power for ten seconds, then check for a pending firmware update.",
     "S. Devi", "Checked 6 weeks ago", False, 22, "Live", "laptop wake sleep screen slow"),
    ("KB-0042", "Replaying a failed invoice batch",
     "Re-pin the certificate, then replay from the admin console. Confirm the count.",
     "L. Chen", "Checked 4 days ago", False, 14, "Live", "invoice erp batch export report"),
    ("KB-0025", "Connecting to depot wifi on a personal phone",
     "Use the guest network. The floor network is for scanners only.",
     "A. Okonkwo", "Untouched for 8 months", True, 11, "Stale", "wifi personal phone depot guest"),
    ("KB-0039", "Requesting ERP roles and what each one gives you",
     "Invoicing, stock and purchasing are separate. Ask for the narrowest one that works.",
     "Nobody", "Untouched for 11 months", True, 9, "Stale", "erp role access request"),
    ("KB-0051", "Meeting room displays, cables and casting",
     "HDMI first, casting second. The 3rd floor rooms need the dongle.",
     "R. Patel", "Checked 5 weeks ago", False, 7, "Live", "meeting room display cable cast"),
    ("KB-0055", "Spotting a phishing email at Meridian",
     "Check the sender domain, never the display name. Forward to the desk, do not delete.",
     "M. Farah", "Checked last week", False, 6, "Live", "phishing email suspicious sender"),
    ("KB-0058", "Stock count app sign-in problems",
     "Being written.", "S. Devi", "Being written", False, 0, "Draft", "stock count app sign in"),
]

CATALOG = [
    ("Get access to something", "Most of these run themselves once approved",
     [("A shared drive or folder", "Name the folder and why you need it.", "One working day", "Your manager approves"),
      ("An ERP role change", "Add or drop invoicing, stock, or purchasing.", "Two working days", "Manager and finance"),
      ("Warehouse scanner sign-in", "Puts you in the scanner group for a depot.", "Four hours", "")]),
    ("Get equipment", "Stock permitting. Otherwise we send the order date",
     [("A replacement scanner", "For a faulty handheld. Send the asset tag if you can read it.", "Two working days", ""),
      ("A laptop or desktop", "New starter, replacement, or an end-of-life upgrade.", "Five working days", "Your manager approves"),
      ("A monitor, dock, or peripheral", "Keyboards, mice, headsets, docks, a second screen.", "Three working days", "")]),
    ("Joiners and leavers", "Start these early. Access always takes longest",
     [("Set up a new starter", "Account, laptop, access and a first-day checklist in one go.", "Five working days", "People Ops confirms"),
      ("Offboard someone", "Revokes access, recovers kit, forwards their mail.", "Same day", "People Ops and manager"),
      ("Move between depots", "Updates location, badge and depot access.", "Two working days", "Your manager approves")]),
]


def already_seeded(session: Session) -> bool:
    return session.exec(select(Ticket)).first() is not None


def seed(session: Session, clock: Clock) -> None:
    """Idempotent: does nothing if tickets already exist."""
    if already_seeded(session):
        return
    now = clock.now()

    for key, name, domain, pos, skills in TEAMS:
        session.add(Team(key=key, name=name, domain=domain, position=pos, skills=skills))
    for tid, name, team, tier, skills, capacity, location, on_leave in TECHS:
        session.add(Technician(
            id=tid, name=name, team_key=team, tier=tier, skills=skills,
            capacity=capacity, location=location, on_leave=on_leave,
        ))

    for impact, row in policy.DEFAULT_MATRIX.items():
        for urgency, prio in row.items():
            session.add(MatrixCell(impact=impact, urgency=urgency, priority=prio))
    for rule in policy.DEFAULT_SLA_RULES:
        session.add(SlaRuleRow(
            order=rule.order, priority=rule.priority,
            response_minutes=rule.response_minutes,
            resolution_minutes=rule.resolution_minutes, calendar=rule.calendar,
        ))

    for row in TICKETS:
        (tid, subject, requester, dept, impact, urgency, category, team, assignee,
         status, age, major, hold, problem, service, ci) = row
        opened = now - timedelta(minutes=age)
        kind = policy.INCIDENT if tid.startswith("INC-") else policy.REQUEST
        session.add(Ticket(
            id=tid, kind=kind, subject=subject, requester=requester, department=dept,
            impact=impact, urgency=urgency, category=category, team_key=team,
            assignee_id=assignee, status=status, major=major, hold_reason=hold,
            problem_id=problem or None, service=service, affected_ci=ci,
            opened_at=opened,
            paused_at=opened + timedelta(minutes=age // 2) if status == "on_hold" else None,
        ))
        matrix_priority = policy.DEFAULT_MATRIX[impact][urgency]
        session.add(Event(
            ticket_id=tid, at=opened, actor=requester, actor_kind="person",
            field="created", old_value="", new_value=tid,
            reason="raised from the staff portal",
        ))
        session.add(Event(
            ticket_id=tid, at=opened, actor="Relay", actor_kind="judgment",
            field="impact", old_value="", new_value=impact,
            reason="read off the wording at intake, nobody has checked it",
        ))
        session.add(Event(
            ticket_id=tid, at=opened, actor="Relay", actor_kind="judgment",
            field="urgency", old_value="", new_value=urgency,
            reason="read off the wording at intake, nobody has checked it",
        ))
        session.add(Event(
            ticket_id=tid, at=opened, actor="Relay", actor_kind="system",
            field="priority", old_value="", new_value=matrix_priority,
            reason=f"{impact} against {urgency} in the matrix",
        ))
        if hold:
            session.add(Event(
                ticket_id=tid, at=opened + timedelta(minutes=age // 2),
                actor="Relay", actor_kind="system", field="status",
                old_value="in_progress", new_value="on_hold",
                reason=f"{hold}; the fix clock pauses, the reply clock does not",
            ))

    for ticket_id, offset, author, visibility, body, state, reason in CONVERSATION:
        base = next(r for r in TICKETS if r[0] == ticket_id)
        opened = now - timedelta(minutes=base[10])
        session.add(Message(
            ticket_id=ticket_id, at=opened + timedelta(minutes=offset), author=author,
            visibility=visibility, body=body, review_state=state, review_reason=reason,
        ))

    for row in PROBLEMS:
        session.add(Problem(
            id=row[0], title=row[1], state=row[2], since=row[3], root_cause=row[4],
            workaround=row[5], change_id=row[6], owner=row[7], severity=row[8],
        ))
    for row in CHANGES:
        session.add(Change(
            id=row[0], title=row[1], risk=row[2], window=row[3], day_index=row[4],
            day_name=row[5], day_number=row[6], collision=row[7],
            awaiting_board=row[8], frozen_day=row[9], release_id=row[10],
        ))
    for row in RELEASES:
        session.add(Release(
            id=row[0], name=row[1], window=row[2], stage=row[3],
            risk=row[4], owner=row[5], note=row[6],
        ))
    for row in ARTICLES:
        session.add(Article(
            id=row[0], title=row[1], body=row[2], owner=row[3], reviewed_note=row[4],
            stale=row[5], deflected=row[6], state=row[7], keywords=row[8],
        ))
    pos = 0
    for group, note, items in CATALOG:
        for name, blurb, turnaround, approval in items:
            pos += 1
            session.add(CatalogItem(
                group_name=group, group_note=note, name=name, blurb=blurb,
                turnaround=turnaround, approval=approval, position=pos,
            ))

    session.commit()

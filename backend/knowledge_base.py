"""IT support knowledge base: seed data and database helpers.

The seed data is inserted automatically on application startup, but only if
the knowledge_base table is empty (seeding is idempotent, so restarting the
server never duplicates articles or overwrites the database).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import KnowledgeArticle

SEED_ARTICLES: list[dict[str, str]] = [
    {
        "title": "Wi-Fi not connecting",
        "description": (
            "The laptop or phone can see the Wi-Fi network but fails to connect, keeps "
            "asking for the password, or connects and immediately drops."
        ),
        "solution": (
            "1. Toggle Wi-Fi off and on, then restart the device.\n"
            "2. Forget the network and reconnect, re-typing the password carefully.\n"
            "3. Restart the router: unplug it for 30 seconds and plug it back in.\n"
            "4. Make sure you are on the correct network name (SSID); try the 2.4 GHz "
            "band, which reaches farther than 5 GHz.\n"
            "5. Disable and re-enable the wireless adapter in the network settings.\n"
            "6. On corporate Wi-Fi, re-enroll the device or contact IT if the "
            "certificate may have expired."
        ),
        "keywords": "wifi, wi-fi, wireless, network, connect, connection, disconnect, dropping, ssid, hotspot, adapter",
    },
    {
        "title": "Slow internet speeds",
        "description": (
            "Web pages load slowly or time out even though the device is connected to "
            "the network; video calls freeze and downloads crawl."
        ),
        "solution": (
            "1. Run a speed test and compare the result with what your plan promises.\n"
            "2. Restart the router/modem.\n"
            "3. Move closer to the router or use a wired Ethernet connection.\n"
            "4. Close bandwidth-heavy applications and pause large downloads, cloud "
            "syncs and updates.\n"
            "5. Test with another device to isolate whether the problem is the "
            "connection or the machine.\n"
            "6. Switch to a different Wi-Fi channel or the 5 GHz band.\n"
            "7. If speeds stay far below your plan, escalate to your ISP or IT."
        ),
        "keywords": "slow, internet, speed, bandwidth, buffering, loading, pages, browsing, ethernet, router",
    },
    {
        "title": "Computer running slowly",
        "description": (
            "Windows or macOS takes a long time to boot, applications open slowly and "
            "everything generally feels sluggish."
        ),
        "solution": (
            "1. Restart the machine - this clears leaked memory and stuck processes.\n"
            "2. Open Task Manager (Windows) or Activity Monitor (macOS) and close "
            "processes that consume most CPU or memory.\n"
            "3. Check free disk space and keep at least 10-15% of the drive free.\n"
            "4. Disable unnecessary startup programs.\n"
            "5. Install pending operating system and driver updates.\n"
            "6. Run a malware scan.\n"
            "7. If memory is permanently maxed out, request a RAM upgrade or a newer "
            "machine from IT."
        ),
        "keywords": "slow, performance, computer, pc, laptop, boot, startup, sluggish, cpu, memory, ram, lag, freeze",
    },
    {
        "title": "Printer not printing",
        "description": (
            "Print jobs sit in the queue forever, nothing comes out of the printer, or "
            "the printer shows as offline."
        ),
        "solution": (
            "1. Check that the printer is powered on and shows 'ready'/'online'.\n"
            "2. Cancel all stuck jobs to clear the print queue.\n"
            "3. Make sure the correct printer is set as the default.\n"
            "4. Check the USB cable or Wi-Fi connection, plus paper, toner and ink "
            "levels.\n"
            "5. Restart the print spooler service (Windows) or the print system (macOS).\n"
            "6. Remove and re-add the printer.\n"
            "7. Update or reinstall the printer driver."
        ),
        "keywords": "printer, printing, print, queue, spooler, offline, paper, toner, ink, driver, jobs",
    },
    {
        "title": "Password reset or locked account",
        "description": (
            "The user cannot sign in: forgotten password, too many failed attempts, or "
            "expired credentials."
        ),
        "solution": (
            "1. Use the 'Forgot password' link or the self-service reset portal.\n"
            "2. If the account is locked after failed attempts, wait for the automatic "
            "unlock or ask an administrator to unlock it.\n"
            "3. Check Caps Lock and the keyboard layout before typing the password "
            "again.\n"
            "4. After a successful reset, update saved passwords in browsers and mail "
            "clients.\n"
            "5. If sign-in still fails, contact IT with your username and the exact "
            "error message."
        ),
        "keywords": "password, reset, locked, account, login, log in, sign in, sign-in, credentials, forgot, access, username, mfa",
    },
    {
        "title": "DNS problem - websites not resolving",
        "description": (
            "Websites fail to open with 'site can't be reached' or DNS errors such as "
            "'server DNS address could not be found'."
        ),
        "solution": (
            "1. Try a couple of different sites and a different device to scope the "
            "problem.\n"
            "2. Flush the local DNS cache (ipconfig /flushdns on Windows).\n"
            "3. Temporarily switch to public DNS servers such as 8.8.8.8 or 1.1.1.1.\n"
            "4. Restart the router.\n"
            "5. Check for a proxy, VPN or hosts-file entry that could interfere.\n"
            "6. If only internal company names fail, contact IT - the internal DNS "
            "server may be down."
        ),
        "keywords": "dns, resolve, resolution, website, websites, domain, name, server not found, address, probe",
    },
    {
        "title": "VPN not connecting",
        "description": (
            "The VPN client fails to connect, hangs on 'connecting', or disconnects "
            "shortly after connecting."
        ),
        "solution": (
            "1. Confirm the plain internet connection works without the VPN.\n"
            "2. Restart the VPN client and then the whole machine.\n"
            "3. Update the VPN client to the latest version.\n"
            "4. Check username, password, MFA code and certificate expiry.\n"
            "5. Try a different server/endpoint or protocol if your client allows it.\n"
            "6. Temporarily disable security software that may block the tunnel.\n"
            "7. If it still fails, send the client logs to IT."
        ),
        "keywords": "vpn, remote, tunnel, connect, connection, certificate, mfa, timeout, disconnect, client",
    },
    {
        "title": "Blue screen (BSOD) or system crashes",
        "description": (
            "Windows shows a blue screen with a stop code and restarts, or the machine "
            "freezes/crashes unexpectedly."
        ),
        "solution": (
            "1. Write down the stop code shown on the blue screen.\n"
            "2. Uninstall software, drivers or hardware that was added recently.\n"
            "3. Install pending Windows updates and driver updates.\n"
            "4. Run the Windows memory diagnostic and 'chkdsk' to test RAM and disk.\n"
            "5. If it will not start normally, boot into Safe Mode and undo recent "
            "changes.\n"
            "6. Check for overheating and dust-clogged fans.\n"
            "7. Escalate to IT with the stop code and what changed before the crash."
        ),
        "keywords": "blue screen, bsod, crash, crashed, freeze, frozen, restart, reboot, stop code, error, memory, diagnostic",
    },
    {
        "title": "Application not responding",
        "description": (
            "An application freezes with '(Not Responding)' in the title bar, hangs "
            "indefinitely or has to be force-quit."
        ),
        "solution": (
            "1. Wait a minute - some long operations temporarily block the window.\n"
            "2. Force-quit via Task Manager (Windows) or Force Quit (macOS), then "
            "reopen the app.\n"
            "3. Check for and install application updates.\n"
            "4. Disable add-ins/plugins, especially in Office and browsers.\n"
            "5. Clear the application cache or reset its settings.\n"
            "6. Reinstall the application if the problem persists.\n"
            "7. If many apps freeze at once, treat it as a system resource problem "
            "(see 'Computer running slowly')."
        ),
        "keywords": "application, app, program, not responding, frozen, freeze, hang, hangs, force quit, unresponsive, crashed",
    },
    {
        "title": "Email not syncing (Outlook)",
        "description": (
            "Outlook or the mail app stops receiving or sending mail, is stuck on "
            "'Connecting...', or messages pile up in the Outbox."
        ),
        "solution": (
            "1. Check that the internet connection and the mail service status page "
            "are fine.\n"
            "2. Restart the mail client (and the computer if needed).\n"
            "3. Re-authenticate: sign out and back in, or update the saved password "
            "after a reset.\n"
            "4. In Outlook, make sure 'Work Offline' mode is turned off.\n"
            "5. Delete large/stuck messages from the Outbox.\n"
            "6. Check the mailbox quota - a full mailbox stops sending.\n"
            "7. Recreate the mail profile if the account refuses to connect."
        ),
        "keywords": "email, mail, outlook, sync, syncing, inbox, outbox, sending, receiving, exchange, quota, stuck",
    },
    {
        "title": "Browser running slowly or crashing",
        "description": (
            "The browser is slow, freezes, crashes, shows certificate warnings, or "
            "websites behave incorrectly."
        ),
        "solution": (
            "1. Update the browser to the latest version.\n"
            "2. Clear the cache and cookies.\n"
            "3. Disable suspicious or unused extensions.\n"
            "4. Try private/incognito mode and another browser to isolate the cause.\n"
            "5. For certificate errors, check that the system date and time are "
            "correct.\n"
            "6. Check proxy settings and remove unknown proxies.\n"
            "7. Reset browser settings as a last resort."
        ),
        "keywords": "browser, chrome, edge, firefox, cache, cookies, extension, certificate, crash, crashing, slow, proxy, pages",
    },
    {
        "title": "Low disk space",
        "description": (
            "The operating system warns that the disk is almost full; downloads, "
            "updates and saves start to fail."
        ),
        "solution": (
            "1. Open storage settings to see what consumes the space.\n"
            "2. Empty the Recycle Bin/Trash and the Downloads folder.\n"
            "3. Run Disk Cleanup or enable Storage Sense (Windows).\n"
            "4. Uninstall applications you no longer use.\n"
            "5. Move large media/archive files to cloud or external storage.\n"
            "6. Clear temporary files (%temp% on Windows).\n"
            "7. Aim to keep at least 10-15% of the system drive free."
        ),
        "keywords": "disk, space, storage, full, low, cleanup, drive, c:, windows update, temp",
    },
    {
        "title": "USB device not recognized",
        "description": (
            "Windows pops up 'USB device not recognized', or a mouse/keyboard/external "
            "drive is plugged in but does not appear."
        ),
        "solution": (
            "1. Try a different USB port and, if possible, a different cable.\n"
            "2. Test the device on another computer to rule out hardware failure.\n"
            "3. Open Device Manager and look for warning icons on the device.\n"
            "4. Uninstall the device in Device Manager and let Windows reinstall the "
            "driver automatically.\n"
            "5. Restart the computer.\n"
            "6. For bus-powered external drives, use a powered USB hub."
        ),
        "keywords": "usb, device, not recognized, port, drive, peripheral, mouse, keyboard, driver, cable",
    },
    {
        "title": "Laptop battery not charging or draining fast",
        "description": (
            "The laptop only works when plugged in, shows 'plugged in, not charging', "
            "or the battery drains unusually quickly."
        ),
        "solution": (
            "1. Reseat the charger on both ends and try another wall outlet.\n"
            "2. Inspect the cable and connector for damage.\n"
            "3. Run the battery hardware diagnostic (built into most laptops).\n"
            "4. Reduce screen brightness and close background applications.\n"
            "5. Update BIOS and battery drivers from the manufacturer.\n"
            "6. If battery health is poor, arrange a battery replacement."
        ),
        "keywords": "battery, charging, charge, power, laptop, plugged in, drain, draining, adapter, bios",
    },
]


def seed_knowledge_base(db: Session) -> int:
    """Insert the seed articles if the table is empty.

    Returns the number of articles added (0 when the table already had data).
    """
    count = db.execute(select(func.count()).select_from(KnowledgeArticle)).scalar_one()
    if count:
        return 0
    for article in SEED_ARTICLES:
        db.add(KnowledgeArticle(**article))
    db.commit()
    return len(SEED_ARTICLES)


def get_articles(db: Session) -> list[KnowledgeArticle]:
    """Return all knowledge-base articles, ordered by id for stability."""
    return list(db.execute(select(KnowledgeArticle).order_by(KnowledgeArticle.id)).scalars())


def count_articles(db: Session) -> int:
    """Return the number of knowledge-base articles."""
    return db.execute(select(func.count()).select_from(KnowledgeArticle)).scalar_one()

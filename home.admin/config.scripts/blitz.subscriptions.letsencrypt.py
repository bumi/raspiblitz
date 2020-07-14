#!/usr/bin/python3

import sys
import locale
import requests
import json
import math
import time
import datetime, time
import subprocess
import codecs, grpc, os
from pathlib import Path
import toml
from blitzpy import RaspiBlitzConfig

####### SCRIPT INFO #########

# - this subscription does not require any payments
# - the recurring part is managed by the lets encrypt ACME script

# display config script info
if len(sys.argv) <= 1 or sys.argv[1] == "-h" or sys.argv[1] == "help":
    print("# manage letsencrypt HTTPS certificates for raspiblitz")
    print("# blitz.subscriptions.letsencrypt.py create-ssh-dialog")
    print("# blitz.subscriptions.ip2tor.py subscriptions-new dyndns|ip duckdns|freedns id token")
    print("# blitz.subscriptions.ip2tor.py subscriptions-list")
    print("# blitz.subscriptions.ip2tor.py subscription-detail id")
    print("# blitz.subscriptions.ip2tor.py subscription-cancel id")
    sys.exit(1)

####### BASIC SETTINGS #########

SUBSCRIPTIONS_FILE="/mnt/hdd/app-data/subscriptions/subscriptions.toml"

cfg = RaspiBlitzConfig()
cfg.reload()

# todo: make sure that also ACME script uses TOR if activated
session = requests.session()
if cfg.run_behind_tor:
  session.proxies = {'http':  'socks5h://127.0.0.1:9050', 'https': 'socks5h://127.0.0.1:9050'}

####### HELPER CLASSES #########

class BlitzError(Exception):
    def __init__(self, errorShort, errorLong="", errorException=None):
        self.errorShort = str(errorShort)
        self.errorLong = str(errorLong)
        self.errorException = errorException

####### HELPER FUNCTIONS #########

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def handleException(e):
    if isinstance(e, BlitzError):
        eprint(e.errorLong)
        eprint(e.errorException)
        print("error='{0}'".format(e.errorShort))
    else:
        eprint(e)
        print("error='{0}'".format(str(e)))
    sys.exit(1)

def getsubdomain(fulldomainstring):
    return fulldomainstring.split('.')[0]

####### API Calls to DNS Servcies #########

def duckDNSupdate(domain, token, ip):

    print("# duckDNS update IP API call")
    
    # make HTTP request
    try:
        url="https://www.duckdns.org/update?domains={0}&token={1}&ip={2}".format(getsubdomain(domain), token, ip)
        response = session.get(url)
    except Exception as e:
        raise BlitzError("failed HTTP request",url,e)
    if response.status_code != 200:
        raise BlitzError("failed HTTP code",response.status_code)
    
    return response.content

####### PROCESS FUNCTIONS #########

def subscriptionsNew(ip, dnsservice, id, token):

    # check if id already exists
    if len(getSubscription(id)) > 0:
        raise BlitzError("id already exists", id)

    # make sure lets encrypt client is installed
    os.system("/home/admin/config.scripts/bonus.letsencrypt.sh on")

    # dyndns
    realip=ip
    if ip == "dyndns":
        # todo: activate DynDNS (set in raspiBlitz Config the update url)
        realip=cfg.public_ip

    # update DNS with actual IP
    if dnsservice == "duckdns":
        duckDNSupdate(getsubdomain(id), token, realip)

    # todo: run the ACME script
    acmeResult=subprocess.check_output(["/home/admin/config.scripts/bonus.letsencrypt.sh", "issue-cert", "duckdns", "testblitz2.duckdns.org", "056d28ae-d2c4-4e7e-ac66-32f96f3c9eca", "tor"])
    print(acmeResult)
    time.sleep(6)
    if (acmeResult.find("error=") > -1):
        raise BlitzError("letsancrypt acme failed", acmeResult)

    # create subscription data for storage
    subscription = {}
    subscription['type'] = "letsencrypt-v1"
    subscription['id'] = id
    subscription['active'] = True
    subscription['name'] = "{0} for {1}".format(dnsservice, id)
    subscription['dnsservice_type'] = dnsservice
    subscription['dnsservice_token'] = token
    subscription['ip'] = ip
    subscription['time_created'] = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    subscription['warning'] = ""

    # load, add and store subscriptions
    try:
        os.system("sudo chown admin:admin {0}".format(SUBSCRIPTIONS_FILE))
        if Path(SUBSCRIPTIONS_FILE).is_file():
            print("# load toml file")
            subscriptions = toml.load(SUBSCRIPTIONS_FILE)
        else:
            print("# new toml file")
            subscriptions = {}
        if "subscriptions_letsencrypt" not in subscriptions:
            subscriptions['subscriptions_letsencrypt'] = []
        subscriptions['subscriptions_letsencrypt'].append(subscription)
        with open(SUBSCRIPTIONS_FILE, 'w') as writer:
            writer.write(toml.dumps(subscriptions))
            writer.close()

    except Exception as e:
        eprint(e)
        raise BlitzError("fail on subscription storage",subscription, e)

    print("# OK - LETSENCRYPT DOMAIN IS READY")
    return subscription

def subscriptionsCancel(id):

    os.system("sudo chown admin:admin {0}".format(SUBSCRIPTIONS_FILE))
    subs = toml.load(SUBSCRIPTIONS_FILE)
    newList = []
    for idx, sub in enumerate(subs['subscriptions_letsencrypt']):
        if sub['id'] != subscriptionID:
            newList.append(sub)
    subs['subscriptions_letsencrypt'] = newList

    # persist change
    with open(SUBSCRIPTIONS_FILE, 'w') as writer:
        writer.write(toml.dumps(subs))
        writer.close()

    print(json.dumps(subs, indent=2))

    # todo: deinstall letsencrypt if this was last subscription

def getSubscription(subscriptionID):

    try:

        if Path(SUBSCRIPTIONS_FILE).is_file():
            os.system("sudo chown admin:admin {0}".format(SUBSCRIPTIONS_FILE))
            subs = toml.load(SUBSCRIPTIONS_FILE)
        else:
            return []
        if "subscriptions_letsencrypt" not in subs:
            return []
        for idx, sub in enumerate(subs['subscriptions_letsencrypt']):
            if sub['id'] == subscriptionID:
                return sub
        return []
    
    except Exception as e:
        return []

def menuMakeSubscription():

    # todo ... copy parts of IP2TOR dialogs

    ############################
    # PHASE 1: Choose DNS service

    # ask user for which RaspiBlitz service the bridge should be used
    choices = []
    choices.append( ("DUCKDNS", "Use duckdns.org") )

    d = Dialog(dialog="dialog",autowidgetsize=True)
    d.set_background_title("LetsEncrypt Subscription")
    code, tag = d.menu(
        "\nChoose a free DNS service to work with:",
        choices=choices, width=60, height=10, title="Select Service")

    # if user chosses CANCEL
    if code != d.OK:
        sys.exit(0)

    # get the fixed dnsservice string
    dnsservice=tag.lower()

    ############################
    # PHASE 2: Enter ID & API token for service

    if dnsservice == "duckdns":

        # show basic info on duck dns
        Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
If you havent already go to https://duckdns.org
- consider using the TOR browser
- create an account or login
- make sure you have a subdomain added
        ''',title="DuckDNS Account needed")

        # enter the subdomain
        code, text = d.inputbox(
                "Enter yor duckDNS subdomain:",
                height=10, width=40, init="",
                title="DuckDNS Domain")
        subdomain = text.strip()
        subdomain = subdomain.split(' ')[0]
        subdomain = getsubdomain(subdomain)
        domain = "{0}.duckdns.org".format(subdomain)
        os.system("clear")

        # check for valid input
        if len(subdomain) == 0:
            Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
This looks not like a valid subdomain.
        ''',title="Unvalid Input")
            sys.exit(0)

        # enter the token
        code, text = d.inputbox(
                "Enter the duckDNS token of your account:",
                height=10, width=50, init="",
                title="DuckDNS Token")
        token = text.strip()
        token = token.split(' ')[0]

        # check for valid input
        try:
            token.index("-")
        except Exception as e:
            token=""
        if len(token) < 20:
            Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
This looks not like a valid token.
        ''',title="Unvalid Input")
            sys.exit(0)

    else:
        os.system("clear")
        print("Not supported yet: {0}".format(dnsservice))
        time.sleep(4)
        sys.exit(0)      

    ############################
    # PHASE 3: Choose what kind of IP: dynDNS, IP2TOR, fixedIP

    # ask user for which RaspiBlitz service the bridge should be used
    choices = []
    choices.append( ("IP2TOR", "HTTPS for a IP2TOR Bridge") )
    choices.append( ("DYNDNS", "HTTPS for {0} DynamicIP DNS".format(dnsservice.upper())) )
    choices.append( ("STATIC", "HTTPS for a static IP") )

    d = Dialog(dialog="dialog",autowidgetsize=True)
    d.set_background_title("LetsEncrypt Subscription")
    code, tag = d.menu(
        "\nChoose the kind of IP you want to use:",
        choices=choices, width=60, height=10, title="Select Service")

    # if user chosses CANCEL
    if code != d.OK:
        sys.exit(0)

    if tag == "IP2TOR":

        # get all active IP2TOR subscriptions (just in case)
        ip2torSubs=[]
        if Path(SUBSCRIPTIONS_FILE).is_file():
            os.system("sudo chown admin:admin {0}".format(SUBSCRIPTIONS_FILE))
            subs = toml.load(SUBSCRIPTIONS_FILE)
            for idx, sub in enumerate(subs['subscriptions_ip2tor']):
                if sub['active']:
                    ip2torSubs.append(sub)
        
        # when user has no IP2TOR subs yet
        if len(ip2torSubs) == 0:
            Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
You have no active IP2TOR subscriptions.
Create one first and try again.
        ''',title="No IP2TOR available")
            sys.exit(0)  

        # let user select a IP2TOR subscription
        choices = []
        for idx, sub in enumerate(ip2torSubs):
            choices.append( ("{0}".format(idx), "IP2TOR {0} {1}:{2}".format(sub['name'], sub['ip'], sub['port'])) )
        
        d = Dialog(dialog="dialog",autowidgetsize=True)
        d.set_background_title("LetsEncrypt Subscription")
        code, tag = d.menu(
            "\nChoose the IP2TOR subscription:",
            choices=choices, width=60, height=10, title="Select")

        # if user chosses CANCEL
        if code != d.OK:
            sys.exit(0)

        # get the slected IP2TOR bridge
        ip2torSelect=ip2torSubs[int(tag)]
        ip=ip2torSelect["ip"]

    elif tag == "DYNDNS":

        # the subscriptioNew method will handle acrivating the dnydns part
        ip="dyndns"

    elif tag == "STATIC":

        # enter the static IP
        code, text = d.inputbox(
                "Enter the static public IP of this RaspiBlitz:",
                height=10, width=40, init="",
                title="Static IP")
        ip = text.strip()
        ip = token.split(' ')[0]

        # check for valid input
        try:
            ip.index(".")
        except Exception as e:
            ip=""
        if len(ip) == 0:
            Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
This looks not like a valid IP.
        ''',title="Unvalid Input")
            sys.exit(0)

    # create the letsenscript subscription
    try:
        subscription = subscriptionsNew(ip, dnsservice, domain, token)

        # success dialog
        Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
OK your LetsEncrypt subscription is now ready.
Go to SUBSCRIBE > LIST to see details.
Use the correct port on {0}
to reach the service you wanted.
            '''.format(domain),title="OK LetsEncrypt Created")

    except Exception as e:

            # unkown error happend
            Dialog(dialog="dialog",autowidgetsize=True).msgbox('''
Unkown Error happend - please report to developers:
{0}
            '''.format(str(e)),title="Exception on Subscription")
            sys.exit(1)

####### COMMANDS #########

###############
# CREATE SSH DIALOG
# use for ssh shell menu
###############

if sys.argv[1] == "create-ssh-dialog":

    # late imports - so that rest of script can run also if dependency is not available
    from dialog import Dialog

    menuMakeSubscription()
    
    sys.exit()

###############
# SUBSCRIPTIONS NEW
# call from web interface
###############    

if sys.argv[1] == "subscriptions-new":

    # check parameters
    try:
        if len(sys.argv) <= 5: raise BlitzError("incorrect parameters","")
        ip = sys.argv[2]
        dnsservice_type = sys.argv[3]
        dnsservice_id = sys.argv[4]
        dnsservice_token = sys.argv[5]
    except Exception as e:
        handleException(e)

    # create the subscription
    try:
        subscription = subscriptionsNew(ip, dnsservice_type, dnsservice_id, dnsservice_token)
    except Exception as e:
        handleException(e)

    # output json ordered bridge
    print(json.dumps(subscription, indent=2))
    sys.exit()

#######################
# SUBSCRIPTIONS LIST
#######################

if sys.argv[1] == "subscriptions-list":

    try:

        if Path(SUBSCRIPTIONS_FILE).is_file():
            os.system("sudo chown admin:admin {0}".format(SUBSCRIPTIONS_FILE))
            subs = toml.load(SUBSCRIPTIONS_FILE)
        else:
            subs = {}
        if "subscriptions_letsencrypt" not in subs:
            subs['subscriptions_letsencrypt'] = []
        print(json.dumps(subs['subscriptions_letsencrypt'], indent=2))
    
    except Exception as e:
        handleException(e)

    sys.exit(0)

#######################
# SUBSCRIPTION DETAIL
#######################
if sys.argv[1] == "subscription-detail":

    # check parameters
    try:
        if len(sys.argv) <= 2: raise BlitzError("incorrect parameters","")
        subscriptionID = sys.argv[2]
    except Exception as e:
        handleException(e)

    try:
        sub = getSubscription(subscriptionID)
        print(json.dumps(sub, indent=2))

    except Exception as e:
        handleException(e)

    sys.exit(0)

    
#######################
# SUBSCRIPTION CANCEL
#######################
if sys.argv[1] == "subscription-cancel":

    # check parameters
    try:
        if len(sys.argv) <= 2: raise BlitzError("incorrect parameters","")
        subscriptionID = sys.argv[2]
    except Exception as e:
        handleException(e)

    try:

        subscriptionsCancel(subscriptionID)

    except Exception as e:
        handleException(e)

    sys.exit(0)

# unkown command
print("# unkown command")
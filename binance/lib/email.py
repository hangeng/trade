import os
from getpass import getuser
import socket
import smtplib

sender = "sol-bot@dell.com"
receiver = "Geng.Han@dell.com"

message_template = """From: <{sender}>
To: <{receiver}
MIME-Version: 1.0
Content-type: text/html
Subject: PowerStore dpsim longevity run report
<font face="Courier New">
<pre>
{message}
</pre>
</font>
"""
#  message_template = """From: <{sender}>
#  To: <{receiver}
#  Subject: grid trading report
#  {message}
#  """


class EmailSender(object):
    def __init__(self):
        self.this_user = None
        try:
            self.sender = sender
            self.receivers = [receiver]
            self.this_user = getuser()
            self.hostname = socket.gethostname()
            for remote_hostname in ("mailserver.xiolab.lab.emc.com", "mailhub.lss.emc.com"):
                rc = os.system("ping -c 1 -w 2 {0} >/dev/null 2>&1".format(remote_hostname))
                if rc == 0:
                    self.smtpObj = smtplib.SMTP(remote_hostname, timeout=2)
                    return
            self.smtpObj = None
        except Exception:
            pass

    def send(self, message):
        if self.smtpObj is None:
            return
        try:
            message = message_template.format(sender=sender, receiver=receiver, message=message)
            self.smtpObj.sendmail(self.sender, self.receivers, message)
        except Exception:
            pass

if __name__ == "__main__":
    email_sender = EmailSender()
    email_sender.send("This is the email body")

Make sure you check these scripts carefully before using. There will be many places you need to replace benvallack with your username or other changes. 

Add the scripts to your crontab to run like this:
*/1 * * * * /Users/benvallack/imessage_responder/responder.sh >> /Users/benvallack/imessage_responder/autoreply.log 2>&1
*/1 * * * * /opt/local/bin/python3 /Users/benvallack/imessage_responder/openairesponder_mega.py >> /Users/benvallack/imessage_responder/responder.log 2>&1



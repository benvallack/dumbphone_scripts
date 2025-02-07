#!/bin/bash
# Replace the paths and bevallack with your local user below
# Define the numbers you want to track, this can be numbers or emails
#
TARGET_NUMBERS=("1234" "1234 ")
escaped_targets=$(IFS='|'; echo "${TARGET_NUMBERS[*]}")


#                Ruben                    Doris           Ruben           Mum                         Dad                     Tom                   Gem  


DB_PATH="/Users/benvallack/Library/Messages/chat.db"

sudo -u benvallack sqlite3 "/Users/benvallack/Library/Messages/chat.db" <<EOF > /Users/benvallack/imessage_responder/messages.txt
SELECT
    datetime(message.date/1000000000 + 978307200, 'unixepoch', 'localtime') AS time_sent,
    handle.id AS sender,
    message.text AS content,
    (strftime('%s', 'now') - strftime('%s', datetime(message.date/1000000000 + 978307200, 'unixepoch', 'localtime'))) AS age_seconds
FROM message
LEFT JOIN handle ON message.handle_id = handle.ROWID
WHERE message.is_read = 0
AND is_from_me = 0
AND datetime(message.date/1000000000 + 978307200, 'unixepoch', 'localtime') >= datetime('now', '-10 minutes')
AND (strftime('%s', 'now') - strftime('%s', datetime(message.date/1000000000 + 978307200, 'unixepoch', 'localtime'))) >= 120
ORDER BY message.date DESC;
EOF


grep -E "(${escaped_targets})" /Users/benvallack/imessage_responder/messages.txt | tee /Users/benvallack/imessage_responder/filtered_messages.txt

# This already only outputs frop approved senders. Anything in here is good to be added directly to filtered.
osascript /Users/benvallack/imessage_responder/checkwhatsapp.applescript >> /Users/benvallack/imessage_responder/filtered_messages.txt



#!/bin/bash

# Replace benvallack with your local user account name below
 
OLLAMA_MODEL="llama3.2"  # Change to any local model you prefer

TO_REPLY_FILE="/tmp/to_reply.txt"
REPLIED_FILE="/tmp/replied_today.txt"

# Ensure files exist
sudo -u benvallack touch "$TO_REPLY_FILE"
sudo -u benvallack touch "$REPLIED_FILE"

# Process each message
while IFS='|' read -r time_sent sender content age_seconds; do
    if [[ -z "$content" ]]; then
        continue
    fi

    echo "Checking message from $sender: $content"

    RESPONSE=$(sudo -u benvallack /usr/local/bin/ollama run $OLLAMA_MODEL "Your job is to classify messages. You must only reply with one word: 'Important' or 'General'. For this, an 'important' message is anything relating to a time or place or anything to with any kind of meeting or mutual obligation. Now, classify this message according to the rules: $content")
   echo $RESPONSE
    if [[ "$RESPONSE" == "Important" ]]; then
      echo "Adding to to_reply.txt"
        # Check if we've already replied today
        if ! grep -q "$sender" "$REPLIED_FILE"; then
            sudo -u benvallack echo "$sender" >> "$TO_REPLY_FILE"
        fi
    fi
done < /Users/benvallack/imessage_responder/filtered_messages.txt


set to_send_file to POSIX file "/tmp/to_reply.txt"
set urgent_number to "123456789" -- Your urgent SMS number

-- Ensure necessary files exist
try
    do shell script "test -f /tmp/to_reply.txt || touch /tmp/to_reply.txt"
    do shell script "test -f /tmp/replied_today.txt || touch /tmp/replied_today.txt"
on error errMsg
    log "Error ensuring files exist: " & errMsg
end try

-- Ensure the file is not empty before reading
set to_send_list to {}
try
    -- Check file size to avoid "end of file" error
    set fileSize to (do shell script "stat -f%z /tmp/to_reply.txt")
    if fileSize is not "0" then
        set fileContents to read to_send_file
        set to_send_list to paragraphs of fileContents
    end if
on error errMsg
    log "Error reading file: " & errMsg
    set to_send_list to {} -- Default to empty if read fails
end try

-- Remove empty or whitespace-only lines
set filtered_list to {}
repeat with recipient in to_send_list
    set trimmed_recipient to recipient as text
    if trimmed_recipient is not "" and trimmed_recipient is not " " then
        set end of filtered_list to trimmed_recipient
    end if
end repeat

-- Exit early if no recipients
if (count of filtered_list) is 0 then
    log "No valid recipients found. Exiting script."
    return
end if

try
    tell application "Messages"
        -- Dynamically resolve the iMessage account
        set targetService to id of first account whose service type = iMessage
        
        repeat with recipient in filtered_list
            if recipient is not "" then
                try
                    -- Resolve the participant for the recipient
                    set theBuddy to participant recipient of account id targetService
                    
                    -- Send the message
                    send "I'm away from my main devices right now. If it's urgent please re-send to: " & urgent_number & " You will only receive this message once today. Please note if you are using Apple and want to add this number to your contacts, make sure you add it as a new contact, not the existing contact for me. This is to make sure Messages doesn't just keep defaulting to iMessage and not using the urgent SMS number." to theBuddy
                    
                    -- Log success
                    log "Message sent successfully to " & recipient
                    do shell script "echo " & quoted form of recipient & " >> /tmp/replied_today.txt"
                on error errMsg
                    -- Log error for this recipient
                    log "Failed to send message to " & recipient & ": " & errMsg
                end try
            end if
        end repeat
    end tell

    -- Clear the file after processing
    do shell script "echo '' > /tmp/to_reply.txt"

on error errMsg
    display alert "Error: " & errMsg
end try


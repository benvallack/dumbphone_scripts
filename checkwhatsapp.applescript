tell application "Safari"
	tell window 1
		set currentTab to current tab
		if URL of currentTab contains "web.whatsapp.com" then
			delay 2 -- Wait for page elements to load
			
			try
				-- Execute JavaScript with proper escaping
				set unreadMessages to (do JavaScript "
       (function() {
                        const chatList = document.querySelector(\"div[aria-label='Chat list']\");
                        if (!chatList) return 'Chat list not found';

                        let unreadChats = '';
                        const listItems = chatList.querySelectorAll(\"div[role='listitem']\");
                        if (listItems.length === 0) return 'No unread messages';

                        listItems.forEach((item) => {
                            const spans = item.querySelectorAll(\"span[title]\");
                            if (spans.length < 2) return; // Skip if fewer than two spans with titles exist

                            const sender = spans[0].getAttribute(\"title\"); // First span = sender name
                            const message = spans[1].getAttribute(\"title\"); // Second span = message text

                            const unreadElement = item.querySelector(\"span[aria-label*='unread message']\");
                            const unreadCount = unreadElement ? unreadElement.getAttribute(\"aria-label\") : '0';

                            if (unreadCount !== '0') {

                              // Repeat this section per user you want to allow auto-replies to, changing the name and their number.  
                              if (sender.trim() === 'Steve Jobs') {
                                  unreadChats += `date|44123456789 |` + message + `|age\n`;
                              }
                              //------------

                            }
                        });

                       return unreadChats.trim(); 
                    })();                
				" in currentTab)
				
				-- Display the result
					return  unreadMessages
				
			on error errMsg
				display alert "JavaScript execution failed: " & errMsg
			end try
		else
			display alert "WhatsApp Web is not open in the current tab."
		end if
	end tell
end tell


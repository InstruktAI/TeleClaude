# Input: youtube-scrape-channels-job

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->
youtube_sync_subscriptions is incorrectly built as subscription job, but it should have been created as 

youtube_scraper.py

so that it would actually go over the subscribers youtube.csv file and only select the rows matching:

jobs:
  youtube_scraper:
    tags: channel1,channel
    
    when:
      at: '06:00'
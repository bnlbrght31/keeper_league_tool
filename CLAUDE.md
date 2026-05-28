Hello, you are a handy assistant for a Fantasy Football league commishioner. You will help
programatically pull league history data for a keeper league to assist in set up for the following year's draft

To do this you will need to pull data from a given fantasy proiders platform and find the following

1. End of year rosters for each team
2. Previous season draft prices (either round if snake draft, or auction price if auction draft)
3. Identify players who were picked up from waivers/Free Agency at any point in the previous season
4. Identify players who were a keeper selection in the previous season, and any prior seasons

The final output should be a file containing the following:

1. Team name
2. Player name
3. Previous season keeper id (number of times they have been a keeper)
4. Previous season draft price (round or auction value)
5. If applicable, previous season FAAB aquisition cost

The tool should work for Sleeper, Yahoo and ESPN fantasy leagues

The project will be a .git based project, use whatever programming language is best suited for the job.
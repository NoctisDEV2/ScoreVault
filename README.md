# ScoreVault
Esports match data platform for competitive Valorant communities. Automatically  pulls post-match stats via the Riot API, tracks standings, and drives live  broadcast overlays — all managed through a Discord bot and subscriber dashboard.

ScoreVault is an esports results and broadcast automation platform built for 
amateur Valorant leagues, university teams, and tournament organizers.

Instead of manually logging scores or parsing screenshots, admins provide two 
player Riot IDs (one from each team) and ScoreVault does the rest — resolving 
PUUIDs, finding the shared match, pulling full post-match stats from the official 
Riot API, and storing them in a verified, structured format.

Results flow through a Discord bot for match submission and standings queries, 
a subscriber-gated web dashboard for verification and analytics, and directly 
into broadcast overlays via Google Sheets and vMix — giving volunteer organizers 
a professional production workflow at zero cost to players.

Built with Node.js, Python, Redis, PostgreSQL, and Discord.js. Runs fully 
containerized via Docker Compose.

ScoreVault isn't endorsed by Riot Games and doesn't reflect the views or opinions 
of Riot Games or anyone officially involved in producing or managing Riot Games 
properties. Riot Games, and all associated properties are trademarks or registered 
trademarks of Riot Games, Inc.

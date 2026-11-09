# No Vue dashboard change

g01's `app/javascript/dashboard` source stays as shipped. Do not add a
second Vue client, a North Star panel, or a sponsor form here. Gold, white, the
g01 logo, signup, and the small Community dialog are injected by
`ops/g01_branding.rb` and `branding/`. Community hands the user back to a normal
g01 conversation. This folder is a marker so the overlay does not become a
source fork.

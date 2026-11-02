# Paste this inside the existing `namespace :api -> namespace :v1 -> resources :accounts` block.
# Do not replace Chatwoot's routes file.

namespace :g01 do
  resource :north_star, only: [:show], controller: "/api/v1/g01/north_star"
  resources :sponsors, only: [:create], controller: "/api/v1/g01/sponsors"
end

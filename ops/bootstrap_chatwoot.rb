# Idempotent g01 setup for g01. Run inside the g01 container after db:chatwoot_prepare.
# Creates Jane, the website widget, g01 workspace metadata, and the message webhook.
# Leaves auto-resolve unset so the homestead thread stays open.

require "fileutils"

JANE_EMAIL = "jane@g01.local"
ACCOUNT_NAME = "g01denfleece"
INBOX_NAME = "Homestead"
# The public website. FRONTEND_URL is wherever this g01 process is reached.
SITE_NAME = "g01denfleece.com"
SITE_URL = "https://g01denfleece.com"
OUT_DIR = "/bootstrap/out"
WEBHOOK_BASE_URL = ENV.fetch("JANE_WEBHOOK_URL", "http://jane:8000/webhooks/chatwoot")
WEBHOOK_SECRET = ENV.fetch("G01_CHATWOOT_WEBHOOK_SECRET", "")
WEBHOOK_URL = WEBHOOK_SECRET.empty? ? WEBHOOK_BASE_URL : "#{WEBHOOK_BASE_URL}?token=#{WEBHOOK_SECRET}"
FRONTEND = ENV.fetch("FRONTEND_URL", "http://localhost:3000")

FileUtils.mkdir_p(OUT_DIR)
FileUtils.chmod(0o777, OUT_DIR)
operator_path = File.join(OUT_DIR, "operator.txt")
env_path = File.join(OUT_DIR, "chatwoot.env")

known_password = nil
if File.exist?(operator_path)
  match = File.read(operator_path).match(/password:\s*(\S+)/)
  known_password = match[1] if match
end

account = Account.find_by(name: ACCOUNT_NAME) || Account.create!(name: ACCOUNT_NAME)
settings = (account.settings || {}).dup
settings.delete("auto_resolve_after")
settings.delete("auto_resolve_message")
account.settings = settings
account.auto_resolve_duration = nil if account.has_attribute?(:auto_resolve_duration)
account.save!

# These make ordinary g01 filtering, contacts, and conversation details
# useful without moving authoritative or sensitive g01 records out of Jane.
[
  ["g01-homesteader", "A registered g01 homesteader contact", "#7A5E24"],
  ["g01-homestead", "A g01 homestead conversation", "#B8924A"],
  ["g01-jane", "A private conversation with Jane", "#8C6E2F"],
  ["g01-connection", "A conversation between homesteaders", "#3D5A3D"]
].each do |title, description, color|
  label = account.labels.find_or_initialize_by(title: title)
  label.assign_attributes(description: description, color: color, show_on_sidebar: true)
  label.save!
end

[
  ["g01_member", "g01 member", "contact_attribute", "checkbox", "Mirrors whether this contact is a registered homesteader."],
  ["g01_locality", "g01 locality", "contact_attribute", "text", "Public locality mirror for contact filtering."],
  ["g01_kind", "g01 conversation kind", "conversation_attribute", "text", "Jane or homesteader connection thread."],
  ["g01_topic", "g01 connection topic", "conversation_attribute", "text", "Operator or homesteader supplied connection topic."],
  ["g01_property_id", "g01 property id", "conversation_attribute", "text", "Authoritative property reference held by Jane."],
  ["g01_property_a_id", "g01 first property id", "conversation_attribute", "text", "First property in a peer connection."],
  ["g01_property_b_id", "g01 second property id", "conversation_attribute", "text", "Second property in a peer connection."]
].each do |key, display_name, model, display_type, description|
  definition = account.custom_attribute_definitions.find_or_initialize_by(
    attribute_key: key,
    attribute_model: model
  )
  definition.assign_attributes(
    attribute_display_name: display_name,
    attribute_display_type: display_type,
    attribute_description: description
  )
  definition.save!
end

user = User.from_email(JANE_EMAIL)
created_user = user.nil?
if created_user
  password = known_password || "Jane#{SecureRandom.alphanumeric(10)}aA1!"
  user = User.new(name: "Jane", display_name: "Jane", email: JANE_EMAIL, password: password, password_confirmation: password)
  user.skip_confirmation!
  user.save!
else
  password = known_password
end

AccountUser.find_or_create_by!(account: account, user: user) do |membership|
  membership.role = :administrator
end

channel = account.web_widgets.joins(:inbox).find_by(inboxes: { name: INBOX_NAME })
if channel.nil?
  channel = Channel::WebWidget.create!(
    account: account,
    website_url: SITE_URL,
    widget_color: "#3d5a3d",
    welcome_title: "Jane",
    welcome_tagline: "The homestead thread stays open.",
    pre_chat_form_enabled: true,
    pre_chat_form_options: {
      "pre_chat_message" => "Tell Jane your name. The thread stays open.",
      "pre_chat_fields" => [
        { "field_type" => "standard", "label" => "Full name", "name" => "fullName", "type" => "text", "required" => true, "enabled" => true },
        { "field_type" => "standard", "label" => "Email", "name" => "emailAddress", "type" => "email", "required" => true, "enabled" => true },
        { "field_type" => "standard", "label" => "Phone number", "name" => "phoneNumber", "type" => "text", "required" => false, "enabled" => false }
      ]
    }
  )
end

inbox = channel.inbox || Inbox.create!(account: account, channel: channel, name: INBOX_NAME)
inbox.update!(
  name: INBOX_NAME,
  greeting_enabled: true,
  greeting_message: "I'm Jane. Send your ZIP code, such as 70601 or 72756, and I will attach this open thread to a locality.",
  lock_to_single_conversation: false,
  enable_auto_assignment: true,
  enable_email_collect: false
)
InboxMember.find_or_create_by!(inbox: inbox, user: user)

channel.update!(
  website_url: SITE_URL,
  widget_color: "#7A5E24",
  welcome_title: SITE_NAME,
  welcome_tagline: "Talk with Jane. The thread stays open."
)

# Keep the product guide attached to the widget and safe to rerun. Stable
# slugs let a deployment refresh g01-owned copy without duplicating articles.
help_portal = account.portals.find_or_initialize_by(slug: "g01-guide")
help_portal.assign_attributes(
  name: "g01 Guide",
  page_title: "How to use g01",
  header_text: "Practical help for talking with Jane and your community.",
  homepage_link: SITE_URL,
  color: "#7A5E24",
  archived: false,
  channel_web_widget: channel,
  config: {
    "allowed_locales" => ["en"],
    "default_locale" => "en",
    "draft_locales" => [],
    "layout" => "documentation"
  }
)
help_portal.save!

help_categories = [
  {
    slug: "g01-getting-started",
    name: "Getting started",
    description: "What g01 is and how to work with Jane.",
    position: 10,
    articles: [
      {
        slug: "g01-welcome",
        title: "Welcome to g01",
        description: "A quick introduction to your homestead conversation.",
        position: 10,
        content: <<~HTML
          <p>g01 is a place to work toward a more capable, independent homestead through conversation. Your account opens into a private, ongoing thread with Jane. You do not need to learn a dashboard or fill out a long property profile before asking for help.</p>
          <p>Tell Jane what you are trying to build, fix, grow, automate, contain, or understand. She can help turn that goal into practical next steps using the facts you share about your property, constraints, and priorities.</p>
          <h2>What the homestead is for</h2>
          <p>A homestead is a kind of insurance: a guarantee that your place is not at the whim of quarrels beyond your home. Jane can talk about that with you. Under it, the work is to need less outside help, to make the place beautiful by your own standard, to live from what it produces, to make your own energy, to leak no harmful waste, and to have the property recorded on the financial tools that serve you. She discusses your progress when it helps answer your question or when you ask about it. She offers insurance only for products that have been filed for her, and a local insurer can still be a sponsor.</p>
          <p>You can return to the same conversation at any time. The thread is intended to build useful context instead of making you start over.</p>
        HTML
      },
      {
        slug: "g01-working-with-jane",
        title: "Working with Jane",
        description: "What to ask Jane and how to get useful answers.",
        position: 20,
        content: <<~HTML
          <p>Jane is your conversational guide inside g01. Ask in ordinary language. A useful request can be short: “Help me plan a rainwater system,” “What should I do next in the garden?” or “Find a local sponsor who can make this part.”</p>
          <h2>Give her the facts that matter</h2>
          <p>Share your location, goal, budget, available tools, timing, or other constraints when they affect the answer. Jane does not assume details you have not provided. If information is missing, she may ask a follow-up question.</p>
          <h2>Ask for the form you need</h2>
          <p>You can request a checklist, plan, comparison, explanation, draft message, or recommendation. Ask Jane to revise an answer when your circumstances change.</p>
          <h2>Your homestead record</h2>
          <p>Jane can retain supported facts you tell her so future answers are more relevant. Ask her directly if you want to review your recorded progress or correct a detail.</p>
        HTML
      },
      {
        slug: "g01-messages-audio-files",
        title: "Messages, audio, and files",
        description: "Ways to communicate in a g01 conversation.",
        position: 30,
        content: <<~HTML
          <p>Use text, recorded audio, and file attachments in your conversations. Press the microphone to record, then stop to send. Audio messages remain available in the thread for normal playback, and Jane can understand supported recordings sent to her.</p>
          <p>Files and images can provide context for a project. Include a short note explaining what you want Jane or a peer to notice so the response stays focused.</p>
          <p>If a recording is too quiet or cannot be understood, send it again or follow with a text summary. Never include passwords, payment card numbers, or other secrets in a message or attachment.</p>
        HTML
      }
    ]
  },
  {
    slug: "g01-community-support",
    name: "Community and support",
    description: "Peer conversations, local sponsors, and privacy.",
    position: 20,
    articles: [
      {
        slug: "g01-community-conversations",
        title: "Community conversations",
        description: "Start a peer thread and return to conversations you opened.",
        position: 10,
        content: <<~HTML
          <p>Community creates a conversation between you and another g01 homesteader. Open <strong>Community</strong>, enter the peer’s username and a topic, then choose <strong>Start conversation</strong>.</p>
          <p>g01 does not publish a member directory. Exchange usernames directly with people you intend to contact. The search at the top of the sidebar only finds Community conversations you have already opened; it does not search every member.</p>
          <p>The topic helps both participants understand why the thread was opened. Jane stays out of ordinary peer discussion unless someone addresses her by name.</p>
        HTML
      },
      {
        slug: "g01-local-sponsors",
        title: "Local sponsors and recommendations",
        description: "How Jane helps you find registered local providers.",
        position: 20,
        content: <<~HTML
          <p>Ask Jane when you need a local company, fabricator, supplier, or service for a homestead project. She can recommend an active sponsor registered for your locality even when that company has not appeared earlier in your chat.</p>
          <p>Jane gives you the sponsor’s name and the useful capability information available to g01. Add practical constraints—what you need, where you are, timing, and budget—so she can identify an appropriate option.</p>
          <p>A sponsor listing means the provider participates in g01; it is not a guarantee for every job. Confirm scope, price, availability, licensing, and terms directly with the provider before hiring or purchasing.</p>
        HTML
      },
      {
        slug: "g01-buy-a-sponsorship",
        title: "Buying a sponsorship",
        description: "Start a homestead or local-company sponsorship in chat.",
        position: 25,
        content: <<~HTML
          <p>Say “start sponsorship” in your private conversation with Jane. She asks whether the listing is for your homestead or for a separate local company, then collects the details in ordinary words.</p>
          <p>For a homestead, Jane uses your locality and asks what neighbors should call it, what it offers, whether it is a chain, and which email should receive the payment link. For a company, she asks the company name, where it was founded, what type of company it is, what it makes or sells, whether it is a chain, and the payment email.</p>
          <p>Stripe emails the payment link to that address. Jane also posts the same link in the chat. The listing turns on after Stripe marks the payment paid. Jane says the email was sent only when Stripe or g01 actually accepted it. If no invoice exists, she says so.</p>
          <p>Do not type a card number into the chat. Use the secure Stripe page. Ask Jane whether the sponsorship is active if you want her to read the payment record.</p>
        HTML
      },
      {
        slug: "g01-account-privacy",
        title: "Your account and privacy",
        description: "Who can see conversations and how to protect your account.",
        position: 30,
        content: <<~HTML
          <p>Your conversation with Jane is separate from Community conversations. A peer conversation is available to its participants, while other homesteaders cannot use Community search as a member directory.</p>
          <p>g01 uses information you provide to operate the service, keep useful homestead context, connect approved peers, and make relevant local recommendations. Service administrators may access records when required to operate, support, secure, or troubleshoot the product.</p>
          <p>Use a unique password and the password-reset link on the sign-in page if you lose access. Do not send passwords, payment details, identity documents, or private keys through chat. Use the secure hosted page when g01 asks you to complete payment or identity verification.</p>
          <p>Ask Jane to correct a homestead fact when it is inaccurate. Contact the g01 operator for account-access or service-support issues that Jane cannot resolve.</p>
        HTML
      }
    ]
  }
]

popular_category_ids = []
popular_article_ids = []
help_categories.each do |category_data|
  articles = category_data.delete(:articles)
  category = help_portal.categories.find_or_initialize_by(slug: category_data[:slug], locale: "en")
  category.assign_attributes(category_data.merge(locale: "en"))
  category.save!
  popular_category_ids << category.id

  articles.each do |article_data|
    article = help_portal.articles.find_or_initialize_by(slug: article_data[:slug])
    article.assign_attributes(
      article_data.merge(
        account: account,
        author: user,
        category: category,
        locale: "en",
        status: :published,
        draft_title: nil,
        draft_content: nil
      )
    )
    article.save!
    popular_article_ids << article.id
  end
end

help_portal.update!(
  config: help_portal.config.merge(
    "popular_content" => {
      "en" => {
        "category_ids" => popular_category_ids.first(3),
        "article_ids" => popular_article_ids.first(6)
      }
    }
  )
)

{
  "INSTALLATION_NAME" => SITE_NAME,
  "BRAND_NAME" => SITE_NAME,
  "LOGO" => "/g01-logo.png",
  "LOGO_DARK" => "/g01-logo.png",
  "LOGO_THUMBNAIL" => "/g01-favicon.png",
  "BRAND_URL" => SITE_URL,
  "WIDGET_BRAND_URL" => SITE_URL,
  "DISPLAY_MANIFEST" => false
}.each do |name, value|
  row = InstallationConfig.find_or_initialize_by(name: name)
  row.value = value
  row.save!
end

begin
  logo = "/branding/g01-mark.png"
  if File.exist?(logo)
    inbox.avatar.purge if inbox.avatar.attached?
    inbox.avatar.attach(io: File.open(logo), filename: "g01-mark.png", content_type: "image/png")
  else
    puts "g01 mark was not found at #{logo}"
  end
rescue StandardError => e
  puts "g01 logo was not attached: #{e.message}"
end

begin
  GlobalConfig.clear_cache if defined?(GlobalConfig) && GlobalConfig.respond_to?(:clear_cache)
  Rails.cache.clear
rescue StandardError => e
  puts "g01 brand cache was not cleared: #{e.message}"
end

# Account creation needs this token. Failing bootstrap is safer than bringing up
# a login page whose Create an account action can only return 503.
platform = PlatformApp.find_or_create_by!(name: "g01")
platform.platform_app_permissibles.find_or_create_by!(permissible: account)
platform_access = platform.access_token || platform.create_access_token!
platform_token = platform_access.token
raise "g01 platform token is empty" if platform_token.blank?
raise "g01 bridge secret is empty" if ENV["G01_BRIDGE_SECRET"].blank?

begin
  Redis::Alfred.delete(Redis::Alfred::CHATWOOT_INSTALLATION_ONBOARDING)
rescue StandardError => e
  puts "g01 sign-in was left on the installation screen: #{e.message}"
end

# Remove an older unsigned/tokenized g01 hook before saving the canonical URL.
# Otherwise g01 delivers each message twice and one delivery may 401.
Webhook.where(account: account).where("url LIKE ?", "#{WEBHOOK_BASE_URL}%").where.not(url: WEBHOOK_URL).destroy_all
hook = Webhook.find_by(account: account, url: WEBHOOK_URL) || Webhook.new(account: account, url: WEBHOOK_URL)
hook.subscriptions = ["message_created"]
hook.webhook_type = :account_type
hook.save!

access = AccessToken.find_by(owner: user) || AccessToken.create!(owner: user)
raise "g01 API token is empty" if access.token.blank?
widget_url = "#{FRONTEND}/widget?website_token=#{channel.website_token}"

File.write(env_path, <<~ENV)
  G01_CHATWOOT_API_TOKEN=#{access.token}
  G01_CHATWOOT_PLATFORM_TOKEN=#{platform_token}
  G01_CHATWOOT_ACCOUNT_ID=#{account.id}
  G01_CHATWOOT_INBOX_ID=#{inbox.id}
  G01_JANE_USER_ID=#{user.id}
ENV

password_line = password ? "password: #{password}" : "password: unchanged from the first bootstrap (this file was missing the old password)"
File.write(operator_path, <<~TXT)
  Open the g01 form: #{widget_url}
  Jane signs in at #{FRONTEND}/app
  email: #{JANE_EMAIL}
  #{password_line}
  account_id: #{account.id}
  inbox_id: #{inbox.id}
  jane_user_id: #{user.id}
  Sign in at #{FRONTEND}/app/login
  Admin token: #{ENV.fetch("G01_ADMIN_TOKEN", "")}
  Demo homesteader logins, after Jane starts: homesteaders.txt in this folder
TXT

puts "g01 bootstrap ready"
puts widget_url
puts "operator notes: #{operator_path}"

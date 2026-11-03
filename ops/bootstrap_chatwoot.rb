# Idempotent Chatwoot setup for g01. Run inside the Chatwoot container after db:chatwoot_prepare.
# Creates Jane, the website widget (the only homesteader form), and the message webhook.
# Leaves auto-resolve unset so the homestead thread stays open.

require "fileutils"

JANE_EMAIL = "jane@g01.local"
ACCOUNT_NAME = "g01denfleece"
INBOX_NAME = "Homestead"
# The public website. FRONTEND_URL is wherever this Chatwoot process is reached.
SITE_NAME = "g01denfleece.com"
SITE_URL = "https://g01denfleece.com"
OUT_DIR = "/bootstrap/out"
WEBHOOK_URL = ENV.fetch("JANE_WEBHOOK_URL", "http://jane:8000/webhooks/chatwoot")
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

{
  "INSTALLATION_NAME" => SITE_NAME,
  "BRAND_NAME" => SITE_NAME,
  "LOGO" => "/g01-logo.svg",
  "LOGO_DARK" => "/g01-logo.svg",
  "LOGO_THUMBNAIL" => "/g01-mark.svg",
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

begin
  Redis::Alfred.delete(Redis::Alfred::CHATWOOT_INSTALLATION_ONBOARDING)
rescue StandardError => e
  puts "g01 sign-in was left on the installation screen: #{e.message}"
end

hook = Webhook.find_by(account: account, url: WEBHOOK_URL) || Webhook.new(account: account, url: WEBHOOK_URL)
hook.subscriptions = ["message_created"]
hook.webhook_type = :account_type
hook.save!

access = AccessToken.find_by(owner: user) || AccessToken.create!(owner: user)
raise "g01 Chatwoot API token is empty" if access.token.blank?
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
  Open the Chatwoot form: #{widget_url}
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

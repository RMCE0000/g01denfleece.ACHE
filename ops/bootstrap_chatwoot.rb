# Idempotent Chatwoot setup for g01. Run inside the Chatwoot container after db:chatwoot_prepare.
# Creates Jane, the website widget (the only homesteader form), and the message webhook.
# Leaves auto-resolve unset so the homestead thread stays open.

require "fileutils"

JANE_EMAIL = "jane@g01.local"
ACCOUNT_NAME = "g01denfleece"
INBOX_NAME = "Homestead"
OUT_DIR = "/bootstrap/out"
WEBHOOK_URL = ENV.fetch("JANE_WEBHOOK_URL", "http://jane:8000/webhooks/chatwoot")
FRONTEND = ENV.fetch("FRONTEND_URL", "http://localhost:3000")

FileUtils.mkdir_p(OUT_DIR)
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
    website_url: FRONTEND,
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

hook = Webhook.find_by(account: account, url: WEBHOOK_URL) || Webhook.new(account: account, url: WEBHOOK_URL)
hook.subscriptions = ["message_created"]
hook.webhook_type = :account_type
hook.save!

access = AccessToken.find_by(owner: user) || AccessToken.create!(owner: user)
widget_url = "#{FRONTEND}/widget?website_token=#{channel.website_token}"

File.write(env_path, <<~ENV)
  G01_CHATWOOT_API_TOKEN=#{access.token}
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
TXT

puts "g01 bootstrap ready"
puts widget_url
puts "operator notes: #{operator_path}"

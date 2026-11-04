# Same-origin bridge from the authenticated Chatwoot dashboard to Jane.
# Chatwoot remains the UI and auth owner; no Jane or admin token reaches the browser.
require "json"
require "net/http"
require "uri"

class Api::V1::Accounts::G01CommunityController < Api::V1::Accounts::BaseController
  before_action :require_dashboard_authentication
  before_action :require_g01_account
  before_action :require_community_header
  before_action :require_json_and_same_origin, only: :create

  def index
    relay(:get, "/api/internal/community")
  end

  def create
    payload = params.permit(:member_id, :topic).to_h
    relay(:post, "/api/internal/community/connections", payload)
  end

  private

  def require_dashboard_authentication
    dashboard_headers = %w[access-token client uid].all? { |name| request.headers[name].present? }
    return if dashboard_headers &&
              Current.user.is_a?(User) &&
              request.headers["api_access_token"].blank? &&
              request.authorization.blank?

    render json: { error: "dashboard authentication required" }, status: :unauthorized
  end

  def require_g01_account
    expected = ENV.fetch("G01_CHATWOOT_ACCOUNT_ID", "1").to_i
    return if Current.account&.id == expected && Current.account_user.present?

    render json: { error: "g01 account required" }, status: :forbidden
  end

  def require_community_header
    return if request.headers["X-G01-Requested-With"] == "community-v1"

    render json: { error: "community request header required" }, status: :unprocessable_entity
  end

  def require_json_and_same_origin
    expected_origin = ENV.fetch("FRONTEND_URL", "").sub(%r{/$}, "")
    valid = request.media_type == "application/json" &&
            expected_origin.present? &&
            ActiveSupport::SecurityUtils.secure_compare(request.headers["Origin"].to_s, expected_origin)
    return if valid

    render json: { error: "same-origin JSON request required" }, status: :forbidden
  end

  def relay(method, path, payload = nil)
    secret = ENV.fetch("G01_BRIDGE_SECRET", "")
    raise "G01_BRIDGE_SECRET is not configured" if secret.blank?

    base = URI(ENV.fetch("G01_COMMUNITY_UPSTREAM", "http://jane:8000"))
    uri = URI.join(base.to_s.sub(%r{/$}, "") + "/", path.sub(%r{^/}, ""))
    upstream = method == :post ? Net::HTTP::Post.new(uri) : Net::HTTP::Get.new(uri)
    upstream["Accept"] = "application/json"
    upstream["Content-Type"] = "application/json"
    upstream["X-G01-Bridge-Secret"] = secret
    upstream["X-G01-Account-ID"] = Current.account.id.to_s
    upstream["X-G01-User-ID"] = Current.user.id.to_s
    upstream.body = JSON.generate(payload) if payload

    http = Net::HTTP.new(uri.host, uri.port)
    http.open_timeout = 3
    http.read_timeout = 30
    response = http.request(upstream)
    parsed = JSON.parse(response.body.presence || "{}")
    self.response.headers["Cache-Control"] = "no-store"
    self.response.headers["Vary"] = "access-token, client, uid"
    render json: parsed, status: response.code.to_i
  rescue JSON::ParserError
    render json: { error: "Jane returned an invalid community response" }, status: :bad_gateway
  rescue StandardError => e
    Rails.logger.error("g01 community bridge failed: #{e.class}: #{e.message}")
    render json: { error: "community service unavailable" }, status: :bad_gateway
  end
end

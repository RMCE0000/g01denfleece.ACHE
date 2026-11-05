# Inject the g01 stylesheet into Chatwoot HTML. The Vue bundles stay upstream.
# POST /g01/signup is the login-page account form. Chatwoot's own signup creates
# a separate account, so this forwards to Jane on the g01 account instead.
require "json"
require "net/http"
require "uri"

class G01Branding
  SNIPPET = '<link rel="icon" type="image/png" href="/g01-favicon.png?v=19"><link rel="stylesheet" href="/g01-brand.css?v=19"><script src="/g01-brand.js?v=19"></script>'
  SIGNUP_PATH = "/g01/signup"

  def initialize(app)
    @app = app
  end

  def call(env)
    return proxy_signup(env) if env["REQUEST_METHOD"] == "POST" && env["PATH_INFO"] == SIGNUP_PATH

    status, headers, body = @app.call(env)
    content_type = headers["Content-Type"].to_s
    encoding = headers["Content-Encoding"].to_s
    return [status, headers, body] unless content_type.include?("text/html")
    return [status, headers, body] if encoding.include?("gzip")

    raw = +""
    body.each { |chunk| raw << chunk.to_s }
    body.close if body.respond_to?(:close)
    return [status, headers, [raw]] unless raw.include?("</head>") && !raw.include?("g01-brand.css")

    branded = raw.gsub("Login to Chatwoot", "Sign in to g01")
                 .sub("</head>", "#{SNIPPET}</head>")
    headers = headers.dup
    headers["Content-Length"] = branded.bytesize.to_s
    headers.delete("Transfer-Encoding")
    [status, headers, [branded]]
  end

  def proxy_signup(env)
    length = env["CONTENT_LENGTH"].to_i
    return json_response(413, "signup is too large") if length > 8_000

    raw = env["rack.input"].read(length.positive? ? length : 8_000).to_s
    uri = URI(ENV.fetch("G01_SIGNUP_UPSTREAM", "http://jane:8000/api/signup"))
    http = Net::HTTP.new(uri.host, uri.port)
    http.open_timeout = 5
    http.read_timeout = 30
    request = Net::HTTP::Post.new(uri.request_uri)
    request["Content-Type"] = "application/json"
    request["Accept"] = "application/json"
    request.body = raw
    response = http.request(request)
    body = response.body.to_s
    [response.code.to_i, { "Content-Type" => "application/json; charset=utf-8", "Cache-Control" => "no-store" }, [body]]
  rescue StandardError
    json_response(502, "signup could not reach Jane")
  end

  def json_response(status, detail)
    body = JSON.generate({ "detail" => detail })
    [status, { "Content-Type" => "application/json; charset=utf-8", "Cache-Control" => "no-store" }, [body]]
  end
end

Rails.application.config.middleware.use G01Branding

# The controller is mounted as an overlay beside this initializer. It inherits
# Chatwoot's account authentication and proxies only the narrow community API.
Rails.application.routes.append do
  get "/api/v1/accounts/:account_id/g01/community",
      to: "api/v1/accounts/g01_community#index"
  post "/api/v1/accounts/:account_id/g01/community",
       to: "api/v1/accounts/g01_community#create"
end

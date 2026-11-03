# Inject the g01 stylesheet into Chatwoot HTML. The Vue bundles stay upstream.
class G01Branding
  SNIPPET = '<link rel="stylesheet" href="/g01-brand.css?v=2"><script src="/g01-brand.js?v=1"></script>'

  def initialize(app)
    @app = app
  end

  def call(env)
    status, headers, body = @app.call(env)
    content_type = headers["Content-Type"].to_s
    encoding = headers["Content-Encoding"].to_s
    return [status, headers, body] unless content_type.include?("text/html")
    return [status, headers, body] if encoding.include?("gzip")

    raw = +""
    body.each { |chunk| raw << chunk.to_s }
    body.close if body.respond_to?(:close)
    return [status, headers, [raw]] unless raw.include?("</head>") && !raw.include?("g01-brand.css")

    branded = raw.sub("</head>", "#{SNIPPET}</head>")
    headers = headers.dup
    headers["Content-Length"] = branded.bytesize.to_s
    headers.delete("Transfer-Encoding")
    [status, headers, [branded]]
  end
end

Rails.application.config.middleware.use G01Branding

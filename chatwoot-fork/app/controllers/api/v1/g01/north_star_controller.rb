# frozen_string_literal: true

require "json"
require "net/http"
require "uri"

module Api
  module V1
    module G01
      # Proxy only. Copy into a Chatwoot fork and route it inside the existing
      # authenticated accounts namespace. It does not persist messages.
      class NorthStarController < Api::V1::Accounts::BaseController
        def show
          uri = URI.parse("#{sidecar}/api/properties/by-contact/#{params[:contact_id]}/northstar")
          uri.query = URI.encode_www_form(conversation_id: params[:conversation_id], contact_id: params[:contact_id])
          render_sidecar(Net::HTTP::Get.new(uri), uri)
        end

        private

        def sidecar
          ENV.fetch("JANE_SIDECAR_URL", "http://jane-sidecar:8000")
        end

        def render_sidecar(request, uri)
          http = Net::HTTP.new(uri.host, uri.port)
          http.use_ssl = uri.scheme == "https"
          request["Accept"] = "application/json"
          response = http.request(request)
          body = response.body.to_s
          parsed = body.empty? ? {} : JSON.parse(body)
          render json: parsed, status: response.code.to_i
        end
      end
    end
  end
end

# frozen_string_literal: true

require "json"
require "net/http"
require "uri"

module Api
  module V1
    module G01
      class SponsorsController < Api::V1::Accounts::BaseController
        def create
          uri = URI.parse("#{ENV.fetch('JANE_SIDECAR_URL', 'http://jane-sidecar:8000')}/api/sponsors")
          request = Net::HTTP::Post.new(uri)
          request["Accept"] = "application/json"
          request["Content-Type"] = "application/json"
          request.body = {
            property_id: params[:property_id],
            contact_id: params[:contact_id],
            conversation_id: params[:conversation_id],
            company_name: params[:company_name],
            founding_city: params[:founding_city],
            founding_state: params[:founding_state],
            is_franchise_or_chain: ActiveModel::Type::Boolean.new.cast(params[:is_franchise_or_chain]),
            sourcing_tier: params[:sourcing_tier],
            service_tags: params[:service_tags],
            capabilities_summary: params[:capabilities_summary],
            lat: params[:lat],
            lng: params[:lng],
            promo_code: params[:promo_code]
          }.to_json
          http = Net::HTTP.new(uri.host, uri.port)
          http.use_ssl = uri.scheme == "https"
          response = http.request(request)
          render json: JSON.parse(response.body), status: response.code.to_i
        end
      end
    end
  end
end

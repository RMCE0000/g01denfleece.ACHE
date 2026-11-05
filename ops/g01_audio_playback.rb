# Serve audio bubbles through Active Storage's same-origin proxy. The default
# redirect route may resolve as a downloadable attachment, which lets backend
# transcription fetch the bytes but prevents reliable in-browser playback.
module G01InlineAudioPlayback
  private

  def inline_audio_url
    return "" unless file.attached?

    Rails.application.routes.url_helpers.rails_storage_proxy_path(
      file,
      disposition: "inline"
    )
  end
end

Rails.application.config.to_prepare do
  Attachment.prepend(G01InlineAudioPlayback) unless Attachment < G01InlineAudioPlayback
end

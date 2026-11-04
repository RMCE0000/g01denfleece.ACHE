# Chatwoot contacts are account-wide by default. For homesteader agents, scope
# CRM results to contacts attached to inboxes they can already access. This
# preserves normal contact tools without turning the Contacts page into a
# directory of every registered homesteader.
module G01ContactsScope
  private

  def fetch_contacts(contacts)
    super(g01_visible_contacts(contacts))
  end

  def fetch_contacts_with_has_more(contacts)
    super(g01_visible_contacts(contacts))
  end

  def fetch_contact
    return super unless g01_homesteader?

    scope = g01_visible_contacts(Current.account.contacts)
    scope = scope.includes(contact_inboxes: [:inbox]) if @include_contact_inboxes
    @contact = scope.find(params[:id])
  end

  def g01_visible_contacts(scope)
    return scope unless g01_homesteader?

    inbox_ids = InboxMember.where(user_id: Current.user.id).select(:inbox_id)
    contact_ids = Conversation.where(account_id: Current.account.id, inbox_id: inbox_ids).select(:contact_id)
    scope.where(id: contact_ids)
  end

  def g01_homesteader?
    return @g01_homesteader if defined?(@g01_homesteader)
    return @g01_homesteader = false unless Current.user.is_a?(User) && Current.account

    sql = ActiveRecord::Base.sanitize_sql_array(
      [
        "SELECT 1 FROM g01_properties WHERE chatwoot_account_id = ? AND chatwoot_user_id = ? LIMIT 1",
        Current.account.id,
        Current.user.id
      ]
    )
    @g01_homesteader = ActiveRecord::Base.connection.select_value(sql).present?
  rescue ActiveRecord::StatementInvalid
    @g01_homesteader = false
  end
end

Rails.application.config.to_prepare do
  controller = Api::V1::Accounts::ContactsController
  controller.prepend(G01ContactsScope) unless controller.ancestors.include?(G01ContactsScope)
end

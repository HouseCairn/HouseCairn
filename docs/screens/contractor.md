# Contractor

The sheet of a contractor, at `/h/<home id>/contractors/<contractor id>/`: name, trade,
phone, email address, address, note, and the tasks that name them.

- **Download the contact (.vcf)** gives a contact file (vCard 3.0, `text/vcard`) that
  iOS, Android, Outlook and Thunderbird import as a new contact. Every member of the home
  can download it, read-only members included. The file name is the contractor's name
  without accents or punctuation, and everything typed in the sheet is escaped, so a note
  cannot add a field to the file.
- **Edit** and **Delete** are for those who can write in the home. Deleting a contractor
  keeps the tasks that named them, without a contractor, and the maintenance contracts of
  the items that named them, without a provider: the number and the link of the contract stay.

The phone number and the email address are links (`tel:` and `mailto:`).

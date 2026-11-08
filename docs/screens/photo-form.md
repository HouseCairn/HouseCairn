# Add a photo

The form to add a photo of a room, at
`/h/<home id>/rooms/<room id>/photos/new/`, or of an item, at
`/h/<home id>/items/<item id>/photos/new/`. From a phone, the file field offers
the camera and the gallery.

| Field | Content |
| --- | --- |
| Photo | A JPEG, PNG or WebP image, 10 MB at most by default (see [Rooms and items](../guides/rooms-and-items.md)). |
| Caption | Optional, 200 characters at most. |
| Category | **General** (the default), **Behind the walls** (pipes and cables photographed before the wall is closed, to know where not to drill), **Before the work**, **After the work** or **Other** (say what it is in the caption). |

HouseCairn checks the content of the file, not its name or the type your browser
announces. It then writes the image again: the location and every other
information stored in the file (camera, date, comments) are removed, a photo
taken in portrait is turned upright and an image over 2,560 pixels is reduced. A
room or an item holds 30 photos at most.

A photo opens at `/h/<home id>/photos/<photo id>/` and its thumbnail at
`/h/<home id>/photos/<photo id>/thumbnail/`, for the members of the home only.
**Delete** under a thumbnail removes the photo from the screens and the API.

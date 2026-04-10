This project is really the foundation of lots of ideas.  Unfortunately, it's brittle.  It needs to store it's configurations in the database.  We need to document the schemas in the database.  We need to make sure it know what directories, file types and metadata are needed, and when differnt stages of post processing are accomplished.

We need to mature this into a simpler to use program, with a ux to configure and use it.  It should self throttle, so that while it runs, it's never a pain in the read for a user.

the program should be informed by uaish, but autograph, using LDA, and TF/IDF, cosine similarity, and decide should this be in postresql with it's vector database or should FAISS be it's view into the embeddings.  When should the FAISS be re indexed.  

Sooo, there are some enhancement requests that shoudl cover what I said.  

For every prompt and AI user does, it should be cleaned and spell checked, and simplified.  It should also be keyword searched against the database, or embeddings search or both, and we should annotate the prompt with local knowledge and why its useful.  This should be likely in a file, and we should never repeat those references from other projects or papers.

Get going this is how AI gets a brain, and long term context.

Mark Menkhus, April 9, 2026.

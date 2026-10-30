-- 1. Create the database
CREATE DATABASE HMI;
GO

-- Use the new database
USE HMI;
GO


CREATE TABLE [dbo].[Users] (
    [Id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [Username] NVARCHAR(50) NOT NULL UNIQUE,
    [full_name] NVARCHAR(100)     NULL,
    [Email]    NVARCHAR(100)     NULL UNIQUE,
    [Password] VARCHAR(255)      NULL,
    [created_at] DATETIME         NOT NULL
        CONSTRAINT DF_Users_CreatedAt DEFAULT (GETDATE())
);
GO

SET IDENTITY_INSERT [dbo].[Users] ON;

INSERT INTO [dbo].[Users] (
    [Id],
    [username],
    [full_name],
    [email],
    [Password],
	[created_at]
)
VALUES
    (3, 'admin',     'Admin User',   'admin@example.com', 'admin',    '2025-06-15 19:00:30.160'),
    (4, 'john_doe',  'John Doe',     'john.doe@example.com', '123', '2025-06-15 19:00:30.160');

SET IDENTITY_INSERT [dbo].[Users] OFF;
GO

CREATE TABLE [dbo].[Emails](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[message_id] [nvarchar](max) NULL,
	[date] [datetime] NULL,
	[from_email] [nvarchar](255) NULL,
	[to_email] [nvarchar](max) NULL,
	[subject] [nvarchar](max) NULL,
	[mime_version] [nvarchar](50) NULL,
	[content_type] [nvarchar](255) NULL,
	[content_transfer_encoding] [nvarchar](255) NULL,
	[x_from] [nvarchar](255) NULL,
	[x_to] [nvarchar](max) NULL,
	[x_cc] [nvarchar](max) NULL,
	[x_bcc] [nvarchar](max) NULL,
	[x_folder] [nvarchar](255) NULL,
	[x_origin] [nvarchar](255) NULL,
	[x_filename] [nvarchar](255) NULL,
	[body] [nvarchar](max) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO

CREATE TABLE [dbo].[CleanedEmails](
	[id] [bigint] NULL,
	[parsed_date] [datetime] NULL,
	[cleaned_body] [varchar](max) NULL,
	[cleaned_from_email] [varchar](max) NULL,
	[cleaned_to_email] [varchar](max) NULL,
	[cleaned_subject] [varchar](max) NULL,
	[cleaned_mime_version] [varchar](max) NULL,
	[cleaned_content_type] [varchar](max) NULL,
	[cleaned_content_transfer_encoding] [varchar](max) NULL,
	[cleaned_x_from] [varchar](max) NULL,
	[cleaned_x_to] [varchar](max) NULL,
	[cleaned_x_cc] [varchar](max) NULL,
	[cleaned_x_bcc] [varchar](max) NULL,
	[cleaned_x_folder] [varchar](max) NULL,
	[cleaned_x_origin] [varchar](max) NULL,
	[cleaned_x_filename] [varchar](max) NULL
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO


CREATE TABLE [dbo].[AnalyzedEmails](
	[id] [bigint] NULL,
	[summary] [varchar](max) NULL,
	[category] [varchar](max) NULL,
	[tags] [varchar](max) NULL
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO




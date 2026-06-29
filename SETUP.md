# Environment Setup

The benchmark is set up to run with PPT Online so that you do not need to install Microsoft PowerPoint locally.
We use OneDrive to access and store benchmark PowerPoint files. Below is the needed setup for this.

## Set Up Your Python Environment
- Make sure you run the project setup in README.md as a prerequisite.
- Install and **ensure your docker daemon is running**: (https://docs.docker.com/)

## Logging into a Microsoft Account
You will need a valid personal Microsoft account with at least (X GB) of space on the attached personal OneDrive.

### Azure Account
You need an Azure account to register the app used for OneDrive access. Perform the following steps on the **Azure Portal**.

> **Disclaimer:** Creating an Azure free trial requires a credit card. The trial itself is free and you will not be charged unless you explicitly upgrade to a paid plan or choose pay-as-you-go.

#### 1. Create a Free Azure Trial Account (or skip if you have an existing personal account)
1. Go to https://azure.microsoft.com/free and click **Start free**.
2. Sign in with a **personal** Microsoft account (or create one).
3. Complete the identity verification steps (phone number and credit card).
4. Agree to the subscription terms and finish sign-up.

#### 2. Create a Tenant in Azure Active Directory
1. Sign in to the Azure Portal: https://portal.azure.com
2. In the top search bar, search for **Microsoft Entra ID** and open it.
3. Verify that the **Default Directory** is selected.
4. If not, create a new tenant by going to **Manage tenants** and choose **+ Create**.

#### 3. Register an App in Azure Portal
1. In the Azure Portal, search for **App registrations** and open it.
2. Click **New registration**.
3. Enter a name for your application, (APPLICATION_NAME).
4. Under **Supported account types**, choose **"Any Entra ID Tenant + Personal Microsoft accounts"**.
5. Leave **Redirect URI** blank and click **Register**.
6. On the app's **Overview** page, copy the **Application (client) ID** to the environment (.env) file and save it as `CLIENT_ID`. This application will be used to access your OneDrive.
7. In the sidebar, click **Manage > Authentication (Preview)**, go to the **Settings** tab, and toggle **Allow public client flows** to **Enabled**. Click **Save**.


## Configuring the OneDrive Root
Benchmark runs default to `/PPTEval` in OneDrive. To override this you can use `--onedrive-root` when running `python -m ppteval.run_benchmark`, and `--root-folder` when hydrating files.

## Hydrate OneDrive Account
Run `python -m ppteval.env_setup.hydrate` to hydrate your OneDrive with the required files.

```sh
python -m ppteval.env_setup.hydrate --root-folder /PPTEval --local-dir data/files/PowerPoint
```

Note: This process will consume space on your OneDrive proportional to the size of `data/files/PowerPoint`.

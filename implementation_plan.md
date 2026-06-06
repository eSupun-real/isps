# Implementation Plan - AI Model Selection & aisstream.io Vessel Tracking

This plan outlines the changes required to allow PFSO configuration of LLM models (and dynamic listing of models available for each provider's API key), integrate the `aisstream.io` API for real-time vessel data lookup, auto-fill vessel details by IMO number, prepend the IMO number to the vessel name in all listings/views, and display the vessel's live position on an interactive map.

## User Review Required

> [!IMPORTANT]
> - **API Key for aisstream.io**: A new configuration field `AISTREAM_API_KEY` will be added to the Configuration page. The user will need to sign up for a free key on [aisstream.io](https://aisstream.io/) and save it there.
> - **Simulated Fallback**: If no key is entered or if the real API request fails/timeouts (standard AIS reports only broadcast every few minutes), the lookup will fall back to realistic mock vessel particulars and positions around Hambantota Port to ensure a working demonstration.

## Proposed Changes

---

### Backend Components

#### [MODIFY] [server/app.py](file:///g:/App_Development/isps/v2/server/app.py)

- **AI Model Selection**:
  - Update `/api/config` endpoints to load, mask, and save the chosen models: `anthropic_model`, `openai_model`, `openrouter_model`.
  - Add an endpoint `/api/config/models` that fetches available models for each configured key:
    - **Anthropic**: Calls `https://api.anthropic.com/v1/models`
    - **OpenAI**: Calls `https://api.openai.com/v1/models`
    - **OpenRouter**: Calls `https://openrouter.ai/api/v1/models`
  - Update `call_llm` to use the model selected in `config.json` (falling back to default models if none is selected).

- **aisstream.io Vessel Data Lookup**:
  - Add an endpoint `/api/vessels/lookup-imo/<imo>` that:
    - Queries the `aisstream.io` WebSocket stream if `AISTREAM_API_KEY` is configured.
    - Standardizes the response fields: `vessel_name`, `gross_tonnage`, `vessel_type`, `flag_state`, `latitude`, `longitude`.
    - If `AISTREAM_API_KEY` is not present, or if the lookup times out (since AIS broadcasts are sparse), falls back to generating a realistic mock vessel data profile based on the IMO code.
  - Store vessel coordinates (latitude/longitude) in the database for each vessel call so that the position is persisted and can be viewed later.
  - Modify `isps_hbt.db` schema: update/add columns for `latitude` and `longitude` in the `vessel_calls` table.

#### [MODIFY] [server/db.py](file:///g:/App_Development/isps/v2/server/db.py)
- Ensure the database initialization script includes the `latitude` and `longitude` columns in the `vessel_calls` table.

---

### Frontend Components

#### [MODIFY] [client/index.html](file:///g:/App_Development/isps/v2/client/index.html)

- **Configuration Screen**:
  - Add inputs/dropdowns for model selection for each provider.
  - Add an "Aisstream.io API Key" password field under Configuration.
  - Fetch and show the list of available models next to each API key.

- **Vessel Name IMO Prefix**:
  - Update `vesselTableHTML`, `loadReviewList`, `openReviewDetail`, `loadNobjList`, and `openNobjDetail` to prepend `(IMO: <imo>)` (or standard `IMO <imo> — ` format) to the vessel name.

- **Vessel Lookup by IMO**:
  - Add a "Lookup IMO" button next to the `s_imo` field on the Submit page.
  - Auto-trigger lookup if a 7-digit IMO number is typed and blurred.
  - Auto-fill `s_name`, `s_gt`, `s_type`, `s_flag` on success.

- **Interactive Map**:
  - Add Leaflet.js dependencies (CSS + JS) in `<head>`.
  - Add map container in Submit page, Review page, and No-Objection page.
  - Display the vessel's current position as a marker on the map whenever coordinates are available.

## Verification Plan

### Automated Tests
- Run `python server/db.py` to migrate/verify the schema.
- Run `python server/app.py` and hit `/api/vessels/lookup-imo/9982990` with and without API keys.

### Manual Verification
- Log in as `pfso_hbt`. Go to Configuration, save API keys, and test the model listing dropdown.
- Log in as `agent_mol`. Create a new vessel call, enter an IMO number, verify that the details are auto-filled, and check the map rendering.
- Log in as `isps_office` / `pfso_hbt`. Verify that the vessel call list, review screen, and no-objection screen prepend the IMO number to the vessel name and show the vessel's position on the map.

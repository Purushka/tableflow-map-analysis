export const RGSSA_TEMPLATE = {
  id: "rgssa",
  name: "RGSSA Map Cataloguing",
  description: "CSV + Map Images → AI Map Analysis (3-level) → AI Cross-Match (4 outputs) → Normalize → AI Geo → AI Desc → B-L → LCSH → Excel",
  category: "plugin" as const,
  nodes: [
    // ══════════════ Input Branch: CSV ══════════════
    {
      id: "n-csv",
      type: "input_csv",
      position: { x: 50, y: 100 },
      data: {
        label: "Maps CSV",
        config: { encoding: "utf-8-sig", delimiter: "," },
      },
    },
    {
      id: "n-fix-enc",
      type: "transform_normalize",
      position: { x: 300, y: 100 },
      data: {
        label: "Fix Encoding",
        config: {
          operations: JSON.stringify([
            { column: "*", function: "fix_encoding" },
          ]),
        },
      },
    },

    // ══════════════ Input Branch: Images ══════════════
    {
      id: "n-images",
      type: "input_images",
      position: { x: 50, y: 400 },
      data: {
        label: "Map Scans (ZIP)",
        config: { max_images: 0 },
      },
    },
    {
      id: "n-ai-map",
      type: "ai_map_analysis",
      position: { x: 300, y: 400 },
      data: {
        label: "AI: 3-Level Map Analysis",
        config: {
          model: "",
          image_column: "file_path",
          max_tokens: 4000,
          concurrency: 0,
        },
      },
    },

    // ══════════════ AI Cross-Match ══════════════
    {
      id: "n-cross-match",
      type: "ai_cross_match",
      position: { x: 600, y: 250 },
      data: {
        label: "AI Cross-Match",
        config: {
          match_mode: "hybrid",
          model: "",
          left_match_columns: "TITLE, Author, Date Published , Call Number, Subject, Description ",
          right_match_columns: "filename, map_title, map_description, map_place_names, map_date, map_date_year",
          system_prompt: "",
          confidence_threshold: 0.50,
          ambiguity_gap: 0.08,
          top_k: 10,
          batch_size: 5,
          max_tokens: 6000,
          concurrency: 0,
        },
      },
    },

    // ══════════════ Matched Branch: Full Pipeline ══════════════
    {
      id: "n-normalize",
      type: "transform_normalize",
      position: { x: 900, y: 100 },
      data: {
        label: "Normalize Fields",
        config: {
          operations: JSON.stringify([
            { column: "Date Published ", output_column: "date_year", function: "date" },
            { column: "Scale", output_column: "scale_clean", function: "scale" },
            { column: "TITLE", output_column: "title_clean", function: "trim" },
            { column: "Call Number", output_column: "bl_parsed", function: "call_number" },
          ]),
        },
      },
    },
    {
      id: "n-score",
      type: "transform_formula",
      position: { x: 1150, y: 100 },
      data: {
        label: "Completeness Score",
        config: {
          output_column: "completeness",
          formula_type: "expression",
          formula: "count_filled([TITLE],[Author],[Date Published ],[Publisher],[Scale],[Subject],[Description ],[Call Number],[Format],[Place of Publication]) / 10 * 100",
        },
      },
    },
    {
      id: "n-ai-geo",
      type: "ai_enrich",
      position: { x: 1400, y: 100 },
      data: {
        label: "AI: Extract Geography",
        config: {
          model: "",
          system_prompt: "You are a map cataloguing assistant. Extract the geographic area that this map DEPICTS (not where it was published).\n\nRules:\n- Return a single-line compact JSON object, no markdown fences\n- Every value must be a simple string, NEVER an array or list\n- For multiple areas, use comma-separated text: \"Europe, Asia\" not [\"Europe\",\"Asia\"]\n- continent: use \"World\" for world maps, or the continent name(s)\n- feature: specific geographic feature shown (e.g. \"World\", \"Mediterranean Sea\", \"Solar System\")\n- If the map covers the whole world, set continent to \"World\"\n- theme: the dominant thematic subject of this map. Examples: \"Political\", \"Topographic\", \"Nautical\", \"Historical\", \"Geological\", \"Commercial\", \"Military\", \"Exploration\", \"Pilgrimage\", \"Celestial\", \"Physical\", \"Transportation\", \"Agricultural\", \"Hydrographic\", \"Cadastral\", \"Pictorial\", \"Aeronautical\", \"Mining\", \"Pastoral\". For general reference maps with no special theme, use \"General\". Always provide a theme value.",
          user_prompt_template: 'Title: {TITLE}\nDescription: {Description }\nPlace of Publication: {Place of Publication}\nSubject: {Subject Refs}\nGIS: {GIS links}\nMap Type: {map_type}\nMap Subject: {map_subject}\nMap Coverage: {map_coverage}\nMap Place Names: {map_place_names}\nMap Coordinates: {map_coordinates}\nMap BBox: W={map_bbox_west} E={map_bbox_east} S={map_bbox_south} N={map_bbox_north}\nMap Description: {map_description}\n\nReturn JSON: {"continent":"","country":"","state":"","city":"","feature":"","theme":""}',
          json_field_mapping: JSON.stringify({
            continent: "geo_continent",
            country: "geo_country",
            state: "geo_state",
            city: "geo_city",
            feature: "geo_feature",
            theme: "primary_theme",
          }),
          max_tokens: 1000,
          batch_mode: true,
          batch_size: 5,
        },
      },
    },
    {
      id: "n-ai-desc",
      type: "ai_enrich",
      position: { x: 1650, y: 100 },
      data: {
        label: "AI: Standardized Description",
        config: {
          model: "",
          system_prompt: "You are a cartographic cataloguing expert. Write a standardized catalog description (2-3 sentences) for this cartographic item.\n\nFormat: [Item type] depicting/showing [geographic coverage]. [Notable features or historical context]. [Physical format summary].\n\nRules:\n- Professional cataloguing language\n- State geographic coverage clearly (world, hemisphere, region, celestial, etc.)\n- Mention projection, publisher, or historical significance if available\n- Include physical format from the Description field if present\n- If information is insufficient, describe what can be inferred from the title\n- IMPORTANT: Always finish your sentences completely — never leave a sentence unfinished\n- Return a single-line compact JSON object with no newlines or extra spaces: {\"standardized_description\":\"your text\"}",
          user_prompt_template: 'Title: {TITLE}\nExisting Description: {Description }\nDate Published: {Date Published }\nAuthor: {Author}\nScale: {Scale}\nPlace of Publication: {Place of Publication}\nSubject: {Subject Refs}\nGIS: {GIS links}\nMap Size: {Map Size Map Team}\nFormat: {Format}\nGeography: continent={geo_continent}, country={geo_country}, feature={geo_feature}, theme={primary_theme}\nMap Type: {map_type}\nMap Medium: {map_medium}\nMap Condition: {map_condition}\nMap Has Insets: {map_has_insets}\nMap Title (from scan): {map_title}\nMap Publisher (from scan): {map_publisher}\nMap Scale (from scan): {map_scale}\nMap Scale Ratio: {map_scale_ratio}\nMap Date (from scan): {map_date}\nMap Year: {map_date_year}\nMap Projection: {map_projection}\nMap Coordinates: {map_coordinates}\nMap BBox: W={map_bbox_west} E={map_bbox_east} S={map_bbox_south} N={map_bbox_north}\nMap Dimensions: {map_width_cm}cm x {map_height_cm}cm\nMap Place Names: {map_place_names}\nMap Legend Content: {map_legend_content}\nMap Notes: {map_notes}\nMap Description: {map_description}\n\nReturn JSON: {"standardized_description": ""}',
          json_field_mapping: JSON.stringify({
            standardized_description: "standardized_description",
          }),
          max_tokens: 2000,
          batch_mode: true,
          batch_size: 5,
        },
      },
    },
    {
      id: "n-bl",
      type: "lookup_bl_area",
      position: { x: 1900, y: 100 },
      data: {
        label: "B-L Area Match",
        config: {
          geo_columns: "geo_city,geo_feature,geo_state,geo_country,geo_continent",
          output_column: "bl_area_matched",
          min_match_length: 5,
        },
      },
    },
    {
      id: "n-lcsh",
      type: "lookup_lcsh",
      position: { x: 2150, y: 100 },
      data: {
        label: "LCSH Generator",
        config: {
          country_col: "geo_country",
          state_col: "geo_state",
          city_col: "geo_city",
          theme_col: "primary_theme",
          output_column: "subject_lcsh",
        },
      },
    },
    {
      id: "n-out-matched",
      type: "output_xlsx",
      position: { x: 2400, y: 100 },
      data: {
        label: "Excel: Matched",
        config: {
          filename: "rgssa_matched.xlsx",
          sheet_name: "Matched",
          freeze_top_row: true,
          auto_filter: true,
        },
      },
    },

    // ══════════════ Ambiguous → Excel (Review) ══════════════
    {
      id: "n-out-ambiguous",
      type: "output_xlsx",
      position: { x: 900, y: 400 },
      data: {
        label: "Excel: Review",
        config: {
          filename: "rgssa_review.xlsx",
          sheet_name: "Ambiguous",
          freeze_top_row: true,
          auto_filter: true,
        },
      },
    },

    // ══════════════ Unmatched Data → Excel ══════════════
    {
      id: "n-out-no-image",
      type: "output_xlsx",
      position: { x: 900, y: 550 },
      data: {
        label: "Excel: No Image",
        config: {
          filename: "rgssa_no_image.xlsx",
          sheet_name: "NoImage",
          freeze_top_row: true,
          auto_filter: true,
        },
      },
    },

    // ══════════════ Unmatched Images → Excel ══════════════
    {
      id: "n-out-no-match",
      type: "output_xlsx",
      position: { x: 900, y: 700 },
      data: {
        label: "Excel: No Match",
        config: {
          filename: "rgssa_no_match.xlsx",
          sheet_name: "NoMatch",
          freeze_top_row: true,
          auto_filter: true,
        },
      },
    },
  ],
  edges: [
    // CSV branch → Fix Encoding → Cross-Match (left)
    { id: "e1", source: "n-csv", sourceHandle: "output", target: "n-fix-enc", targetHandle: "input" },
    { id: "e2", source: "n-fix-enc", sourceHandle: "output", target: "n-cross-match", targetHandle: "left" },
    // Image branch → AI Map Analysis → Cross-Match (right)
    { id: "e3", source: "n-images", sourceHandle: "output", target: "n-ai-map", targetHandle: "input" },
    { id: "e4", source: "n-ai-map", sourceHandle: "output", target: "n-cross-match", targetHandle: "right" },
    // Cross-Match → 4 outputs
    { id: "e5", source: "n-cross-match", sourceHandle: "matched", target: "n-normalize", targetHandle: "input" },
    { id: "e6", source: "n-cross-match", sourceHandle: "ambiguous", target: "n-out-ambiguous", targetHandle: "input" },
    { id: "e7", source: "n-cross-match", sourceHandle: "unmatched_left", target: "n-out-no-image", targetHandle: "input" },
    { id: "e8", source: "n-cross-match", sourceHandle: "unmatched_right", target: "n-out-no-match", targetHandle: "input" },
    // Matched pipeline
    { id: "e9", source: "n-normalize", sourceHandle: "output", target: "n-score", targetHandle: "input" },
    { id: "e10", source: "n-score", sourceHandle: "output", target: "n-ai-geo", targetHandle: "input" },
    { id: "e11", source: "n-ai-geo", sourceHandle: "output", target: "n-ai-desc", targetHandle: "input" },
    { id: "e12", source: "n-ai-desc", sourceHandle: "output", target: "n-bl", targetHandle: "input" },
    { id: "e13", source: "n-bl", sourceHandle: "output", target: "n-lcsh", targetHandle: "input" },
    { id: "e14", source: "n-lcsh", sourceHandle: "output", target: "n-out-matched", targetHandle: "input" },
  ],
};

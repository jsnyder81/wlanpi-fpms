#################################################
# Create a page object that renders dispay page
#################################################
import fpms.modules.wlanpi_oled as oled

from fpms.modules.pages.display import *
from fpms.modules.themes import THEME
from fpms.modules.constants import (
    STATUS_BAR_HEIGHT,
    SMART_FONT,
    FONT11,
    FONT12,
    FONTB11,
    FONTB12,
    MAX_PAGE_LINES,
)

class Page(object):

    def __init__(self, g_vars):

        # grab a screeb obj
        self.display_obj = Display(g_vars)

    def draw_page(self, g_vars, state):

        # Drawing already in progress - return
        if g_vars['drawing_in_progress']:
            return

        # signal we are drawing
        g_vars['drawing_in_progress'] = True

        page_title = state.get("title", "").upper()

        # shorten title if necessary
        if len(page_title) > 15:
            page_title = page_title[:13] + ".."

        # Clear display prior to painting new item
        self.display_obj.clear_display(g_vars)

        # paint the page title
        g_vars['draw'].rectangle((0, 0, PAGE_WIDTH, STATUS_BAR_HEIGHT), fill=THEME.page_title_background.value)
        title_size = FONTB12.getbbox(page_title)
        g_vars['draw'].text(((PAGE_WIDTH - title_size[2])/2, 0), page_title,  font=FONTB12, fill=THEME.page_title_foreground.value)

        # draw back nav indicator
        g_vars['draw'].line([(4, (STATUS_BAR_HEIGHT/2)), (8, 4)], fill=THEME.page_title_foreground.value, width=1)
        g_vars['draw'].line([(4, (STATUS_BAR_HEIGHT/2)), (8, STATUS_BAR_HEIGHT-4)], fill=THEME.page_title_foreground.value, width=1)

        # vertical starting point for menu (under title) & incremental offset for
        # subsequent items
        y = STATUS_BAR_HEIGHT + 1
        y_offset = 14

        # define display window limit for menu table
        table_window = MAX_PAGE_LINES

        menu_items = state.get("items", [])
        option_number_selected = state.get("selected_index", 0)

        # determine the menu list to show based on current selection and window limits
        if (len(menu_items) > table_window):

            # We've got more items than we can fit in our window, need to slice to fit
            if (option_number_selected >= table_window):
                menu_list = menu_items[(option_number_selected - (table_window - 1)): option_number_selected + 1]
                render_selected_index = table_window - 1
            else:
                # We have enough space for the menu items, so no special treatment required
                menu_list = menu_items[0: table_window]
                render_selected_index = option_number_selected
        else:
            menu_list = menu_items
            render_selected_index = option_number_selected

        # paint the menu items, highlighting selected menu item
        for idx, item in enumerate(menu_list):

            nav = item.get("has_children", False)
            sel = (idx == render_selected_index)
            menu_item_name = item.get("name", "")

            rect_fill = THEME.page_item_background.value
            text_fill = THEME.page_item_foreground.value
            nav_fill  = THEME.page_item_foreground.value
            icon_fill = THEME.page_icon_foreground.value
            font_type = FONTB11

            # this is a menu item that has more options
            if nav:
                if len(menu_item_name) > 16:
                    menu_item_name = menu_item_name[:14] + ".."

            # this is selected menu item: highlight it
            if sel:
                rect_fill = THEME.page_selected_item_background.value
                text_fill = THEME.page_selected_item_foreground.value
                nav_fill  = THEME.page_selected_item_foreground.value
                icon_fill = THEME.page_selected_item_foreground.value

            g_vars['draw'].rectangle((0, y, PAGE_WIDTH, y+y_offset), fill=rect_fill)
            g_vars['draw'].text((12, y), menu_item_name,  font=font_type, fill=text_fill)

            if nav:
                # draw list icon
                g_vars['draw'].line([(2, y+(y_offset/2)-2), (2, y+(y_offset/2)-2)], fill=icon_fill, width=1)
                g_vars['draw'].line([(2, y+(y_offset/2)),   (2, y+(y_offset/2))  ], fill=icon_fill, width=1)
                g_vars['draw'].line([(2, y+(y_offset/2)+2), (2, y+(y_offset/2)+2)], fill=icon_fill, width=1)
                g_vars['draw'].line([(4, y+(y_offset/2)-2), (8, y+(y_offset/2)-2)], fill=icon_fill, width=1)
                g_vars['draw'].line([(4, y+(y_offset/2)),   (8, y+(y_offset/2))  ], fill=icon_fill, width=1)
                g_vars['draw'].line([(4, y+(y_offset/2)+2), (8, y+(y_offset/2)+2)], fill=icon_fill, width=1)
                # draw nav indicator
                g_vars['draw'].line([(PAGE_WIDTH - 4, y+(y_offset/2)), (PAGE_WIDTH - 8, y+3)], fill=icon_fill, width=1)
                g_vars['draw'].line([(PAGE_WIDTH - 4, y+(y_offset/2)), (PAGE_WIDTH - 8, y+y_offset-3)], fill=icon_fill, width=1)
            else:
                # draw action icon
                if sel:
                    g_vars['draw'].ellipse((3, y+(y_offset/2)-2, 7, y+(y_offset/2)+2), fill=icon_fill)
                else:
                    g_vars['draw'].ellipse((3, y+(y_offset/2)-2, 7, y+(y_offset/2)+2), outline=icon_fill)

            y += y_offset

        oled.drawImage(g_vars['image'])

        g_vars['drawing_in_progress'] = False
